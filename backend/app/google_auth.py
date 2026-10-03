import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth import exceptions
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from pydantic import EmailStr, TypeAdapter
import requests
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .auth import check_origin, start_session
from .activity import record_activity
from .models import AccessTokenPublic, GoogleIdentity, GoogleLoginRequest, Traveler


def invalid_token():
    return HTTPException(401, "Invalid Google ID token or unverified email.", headers={"Cache-Control": "no-store"})


def verify_google_token(raw: str, client_id: str) -> dict:
    # A fresh transport per call avoids sharing mutable requests sessions across
    # worker threads. Google keys are fetched over HTTPS with a bounded timeout.
    with requests.Session() as transport:
        google_request = GoogleRequest(session=transport)

        def fetch_keys(*args, **kwargs):
            kwargs["timeout"] = 10
            return google_request(*args, **kwargs)

        try:
            claims = id_token.verify_oauth2_token(raw, fetch_keys, audience=client_id)
        except exceptions.TransportError:
            raise HTTPException(503, "Google sign-in is temporarily unavailable.",
                                headers={"Cache-Control": "no-store"}) from None
        except (ValueError, TypeError, KeyError, exceptions.GoogleAuthError):
            raise invalid_token() from None
    # Defense in depth, plus application requirements beyond library verification.
    if (
        claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
        or claims.get("aud") != client_id
        or type(claims.get("exp")) is not int or claims["exp"] <= time.time()
        or claims.get("email_verified") is not True
        or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255
        or not claims["sub"].strip()
    ):
        raise invalid_token()
    try:
        email = str(TypeAdapter(EmailStr).validate_python(claims.get("email"))).lower()
        if len(email) > 254:
            raise ValueError
    except (ValueError, TypeError):
        raise invalid_token() from None
    name = claims.get("name")
    return {"sub": claims["sub"], "email": email,
            "name": name.strip()[:100] if isinstance(name, str) and name.strip() else "Traveler"}


def collision():
    return HTTPException(409, {
        "code": "google_link_required",
        "message": "This email belongs to an existing traveler account. Google sign-in cannot link it automatically. Use the account's existing sign-in method.",
    }, headers={"Cache-Control": "no-store"})


def google_traveler(session: Session, claims: dict) -> Traveler:
    identity = session.get(GoogleIdentity, claims["sub"])
    if identity is None:
        if session.exec(select(Traveler).where(Traveler.email == claims["email"])).first():
            raise collision()
        try:
            # Both inserts roll back together on concurrent subject/email reuse.
            with session.begin_nested():
                traveler = Traveler(name=claims["name"], email=claims["email"], password_hash="")
                session.add(traveler)
                session.flush()
                identity = GoogleIdentity(subject=claims["sub"], traveler_id=traveler.id)
                session.add(identity)
                session.flush()
        except IntegrityError:
            session.rollback()
            identity = session.get(GoogleIdentity, claims["sub"])
            if identity is None:
                raise collision() from None
    # Identify returning accounts by sub only. Do not overwrite the local email
    # or name based on changed claims, or link to a different account by email.
    session.execute(update(Traveler).where(Traveler.id == identity.traveler_id).values(password_hash=Traveler.password_hash))
    traveler = session.get(Traveler, identity.traveler_id)
    if traveler is None:
        raise invalid_token()
    return traveler


def create_google_auth_router(get_session):
    router = APIRouter(prefix="/auth", tags=["Authentication"])
    SessionDep = Annotated[Session, Depends(get_session)]

    @router.post("/google", response_model=AccessTokenPublic, dependencies=[Depends(check_origin)])
    def google_login(data: GoogleLoginRequest, request: Request, response: Response, session: SessionDep):
        client_id = request.app.state.auth_settings.google_client_id
        if not client_id:
            raise HTTPException(503, "Google sign-in is not configured.", headers={"Cache-Control": "no-store"})
        claims = verify_google_token(data.id_token.get_secret_value(), client_id)
        new_account = session.get(GoogleIdentity, claims["sub"]) is None
        traveler = google_traveler(session, claims)
        result = start_session(traveler, request, response, session)
        if new_account:
            record_activity(session, request.app.state.activity_directory, traveler.id,
                            "registration", "google", "success")
        record_activity(session, request.app.state.activity_directory, traveler.id,
                        "sign_in", "google", "success")
        return result

    return router
