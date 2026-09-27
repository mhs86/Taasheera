import hashlib
import secrets
import time
from typing import Annotated
from uuid import uuid4

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import update
from sqlmodel import Session, select

from .config import AuthSettings
from .models import AccessTokenPublic, AuthSession, LoginRequest, RefreshToken, Traveler, TravelerPublic


COOKIE_NAME = "taasheera_refresh"
ISSUER = "taasheera"
AUDIENCE = "taasheera-traveler"
bearer = HTTPBearer(auto_error=False)
# Unknown emails still perform the same bcrypt work as incorrect passwords.
DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds=12))


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def access_token(session: AuthSession, settings: AuthSettings) -> AccessTokenPublic:
    now = int(time.time())
    lifetime = min(settings.access_seconds, session.expires_at - now)
    encoded = jwt.encode(
        {
            "sub": str(session.traveler_id), "sid": session.id, "type": "access",
            "iat": now, "exp": now + lifetime, "iss": ISSUER, "aud": AUDIENCE,
            "jti": str(uuid4()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return AccessTokenPublic(access_token=encoded, expires_in=lifetime)


def set_refresh_cookie(response: Response, raw: str, session: AuthSession, settings: AuthSettings):
    response.set_cookie(
        COOKIE_NAME, raw, max_age=max(0, session.expires_at - int(time.time())),
        path="/auth", httponly=True, secure=settings.cookie_secure, samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_refresh_cookie(response: Response, settings: AuthSettings):
    response.delete_cookie(
        COOKIE_NAME, path="/auth", httponly=True, secure=settings.cookie_secure, samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def check_origin(request: Request):
    # Origin checks also protect against requests from another service on localhost.
    origin = request.headers.get("origin")
    settings = request.app.state.auth_settings
    if (origin is not None and origin not in settings.allowed_origins) or (
        origin is None and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(status_code=403, detail="Origin is not allowed.")


def create_auth_router(get_session):
    router = APIRouter(prefix="/auth", tags=["Authentication"])
    SessionDep = Annotated[Session, Depends(get_session)]

    def current_traveler(
        request: Request,
        session: SessionDep,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Traveler:
        unauthorized = HTTPException(
            status_code=401, detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
        if credentials is None:
            raise unauthorized
        try:
            claims = jwt.decode(
                credentials.credentials, request.app.state.auth_settings.jwt_secret,
                algorithms=["HS256"], issuer=ISSUER, audience=AUDIENCE,
                options={"require": ["sub", "sid", "type", "iat", "exp", "iss", "aud", "jti"]},
            )
            if claims["type"] != "access" or not isinstance(claims["sid"], str):
                raise unauthorized
            auth_session = session.get(AuthSession, claims["sid"])
            if (
                auth_session is None or auth_session.revoked
                or auth_session.expires_at <= int(time.time())
                or str(auth_session.traveler_id) != claims["sub"]
            ):
                raise unauthorized
            traveler = session.get(Traveler, auth_session.traveler_id)
            if traveler is None:
                raise unauthorized
            return traveler
        except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
            raise unauthorized from None

    @router.post("/login", response_model=AccessTokenPublic, dependencies=[Depends(check_origin)])
    def login(data: LoginRequest, request: Request, response: Response, session: SessionDep):
        settings = request.app.state.auth_settings
        # Serialize login with password reset so an old-password login cannot
        # create a new session after reset has revoked existing sessions.
        session.execute(update(Traveler).where(Traveler.email == data.email).values(password_hash=Traveler.password_hash))
        traveler = session.exec(select(Traveler).where(Traveler.email == data.email)).first()
        stored_hash = traveler.password_hash.encode("ascii") if traveler else DUMMY_HASH
        try:
            password = data.password.get_secret_value().encode("utf-8")
            # bcrypt rejects overlong input; still do bcrypt work before rejecting it.
            valid_length = len(password) <= 72
            matches = bcrypt.checkpw(password if valid_length else b"invalid-password", stored_hash)
        except (ValueError, UnicodeError):
            matches = False
            valid_length = False
        if traveler is None or not valid_length or not matches:
            raise HTTPException(
                status_code=401, detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )

        # Replacing a cookie also revokes the previous session in this browser.
        previous = request.cookies.get(COOKIE_NAME)
        if previous:
            old = session.get(RefreshToken, token_hash(previous))
            if old:
                session.execute(update(AuthSession).where(AuthSession.id == old.session_id).values(revoked=True))

        raw = secrets.token_urlsafe(32)
        auth_session = AuthSession(
            id=str(uuid4()), traveler_id=traveler.id, refresh_hash=token_hash(raw),
            expires_at=int(time.time()) + settings.refresh_seconds,
        )
        session.add(auth_session)
        session.flush()
        session.add(RefreshToken(token_hash=auth_session.refresh_hash, session_id=auth_session.id))
        session.commit()
        set_refresh_cookie(response, raw, auth_session, settings)
        return access_token(auth_session, settings)

    @router.get("/me", response_model=TravelerPublic)
    def me(response: Response, traveler: Annotated[Traveler, Depends(current_traveler)]):
        response.headers["Cache-Control"] = "no-store"
        return traveler

    @router.post("/refresh", response_model=AccessTokenPublic, dependencies=[Depends(check_origin)])
    def refresh(request: Request, response: Response, session: SessionDep):
        settings = request.app.state.auth_settings

        def rejected():
            result = JSONResponse(status_code=401, content={"detail": "Invalid or expired refresh token."})
            clear_refresh_cookie(result, settings)
            return result

        raw = request.cookies.get(COOKIE_NAME)
        old = session.get(RefreshToken, token_hash(raw)) if raw else None
        if old is None:
            return rejected()
        auth_session = session.get(AuthSession, old.session_id)
        if auth_session is None:
            return rejected()

        new_raw = secrets.token_urlsafe(32)
        new_hash = token_hash(new_raw)
        # Compare-and-swap: two requests cannot both rotate the same token.
        result = session.execute(
            update(AuthSession).where(
                AuthSession.id == auth_session.id,
                AuthSession.refresh_hash == old.token_hash,
                AuthSession.revoked.is_(False),
                AuthSession.expires_at > int(time.time()),
            ).values(refresh_hash=new_hash).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1 or session.get(Traveler, auth_session.traveler_id) is None:
            # A replay revokes the current replacement token as well.
            session.execute(update(AuthSession).where(AuthSession.id == auth_session.id).values(revoked=True))
            session.commit()
            return rejected()

        session.add(RefreshToken(token_hash=new_hash, session_id=auth_session.id))
        session.commit()
        session.refresh(auth_session)
        set_refresh_cookie(response, new_raw, auth_session, settings)
        return access_token(auth_session, settings)

    @router.post("/logout", status_code=204, dependencies=[Depends(check_origin)])
    def logout(request: Request, session: SessionDep):
        raw = request.cookies.get(COOKIE_NAME)
        old = session.get(RefreshToken, token_hash(raw)) if raw else None
        if old:
            session.execute(update(AuthSession).where(AuthSession.id == old.session_id).values(revoked=True))
            session.commit()
        response = Response(status_code=204)
        clear_refresh_cookie(response, request.app.state.auth_settings)
        return response

    return router
