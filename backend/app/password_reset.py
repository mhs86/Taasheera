"""Email OTP -> short-lived reset grant -> atomic password/session replacement."""

import hashlib
import hmac
import secrets
import time
from typing import Annotated

import bcrypt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import delete, update
from sqlmodel import Session, select

from .auth import check_origin, clear_refresh_cookie, token_hash
from .models import (ActivityEvent, AuthSession, PasswordResetChallenge, PasswordResetConfirm,
                     PasswordResetGrant, PasswordResetRequest, PasswordResetToken,
                     PasswordResetVerify, Traveler)
from .security import admitted, audit, client_address


REQUEST_MESSAGE = {"detail": "If an eligible email/password account exists, a reset code will be sent. Google-only users should recover access through Google."}
INVALID_MESSAGE = "Invalid or expired password reset token."
INVALID_CODE = "Invalid, expired, or already used reset code."
OTP_SECONDS = 600
GRANT_SECONDS = 300
MAX_ATTEMPTS = 5


def code_digest(secret: str, traveler_id: int, nonce: str, code: str) -> str:
    payload = f"password-reset-otp:{traveler_id}:{nonce}:{code}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def deliver_reset(request: Request, recipient: str, code: str, owner: int, nonce: str):
    try:
        request.app.state.reset_sender.send_reset(recipient, code)
        audit(request, "reset-delivery", "accepted", owner)
        return
    except Exception:
        # Provider exceptions can include the complete message. Do not log them.
        pass
    # Use the nonce so a late failure cannot delete a newer resend's code.
    with Session(request.app.state.engine) as session:
        session.execute(delete(PasswordResetChallenge).where(
            PasswordResetChallenge.traveler_id == owner, PasswordResetChallenge.nonce == nonce))
        session.commit()
    audit(request, "reset-delivery", "failed", owner)


def invalid_code():
    return HTTPException(400, INVALID_CODE, headers={"Cache-Control": "no-store"})


def create_password_reset_router(get_session):
    router = APIRouter(prefix="/auth", tags=["Password reset"], dependencies=[Depends(check_origin)])
    SessionDep = Annotated[Session, Depends(get_session)]

    @router.post("/forgot-password", status_code=202)
    def request_reset(data: PasswordResetRequest, request: Request, response: Response,
                      background: BackgroundTasks, session: SessionDep):
        response.headers["Cache-Control"] = "no-store"
        if request.app.state.mail_settings is None:
            audit(request, "reset-request", "unconfigured")
            raise HTTPException(503, "Password reset is not configured.", headers={"Cache-Control": "no-store"})
        allowed = admitted(request, session, [
            ("request-ip", client_address(request), 20, 3600),
            ("email-hour", data.email, 5, 3600),
            ("email-minute", data.email, 1, 60),
            ("mail-global", "deployment", 100, 3600),
        ])
        if not allowed:
            audit(request, "reset-request", "throttled")
            return REQUEST_MESSAGE

        session.execute(update(Traveler).where(Traveler.email == data.email).values(password_hash=Traveler.password_hash))
        traveler = session.exec(select(Traveler).where(Traveler.email == data.email)).first()
        if traveler is not None and traveler.password_enabled:
            now = int(time.time())
            code = f"{secrets.randbelow(1_000_000):06d}"
            nonce = secrets.token_urlsafe(32)
            digest = code_digest(request.app.state.auth_settings.jwt_secret, traveler.id, nonce, code)
            session.execute(delete(PasswordResetChallenge).where(PasswordResetChallenge.expires_at <= now))
            session.execute(delete(PasswordResetChallenge).where(PasswordResetChallenge.traveler_id == traveler.id))
            session.execute(delete(PasswordResetToken).where(PasswordResetToken.traveler_id == traveler.id))
            session.add(PasswordResetChallenge(traveler_id=traveler.id, nonce=nonce,
                                              code_digest=digest, expires_at=now + OTP_SECONDS))
            session.commit()
            background.add_task(deliver_reset, request, traveler.email, code, traveler.id, nonce)
        else:
            session.commit()
        # Keep the same response and request audit for unknown, Google-only and
        # password accounts. Never expose account type from recovery endpoints.
        audit(request, "reset-request", "accepted")
        return REQUEST_MESSAGE

    @router.post("/verify-reset-code", response_model=PasswordResetGrant)
    def verify_code(data: PasswordResetVerify, request: Request, response: Response, session: SessionDep):
        response.headers["Cache-Control"] = "no-store"
        if not admitted(request, session, [
            ("verify-ip", client_address(request), 60, 3600),
            ("verify-email", data.email, 10, 900),
        ]):
            audit(request, "reset-verify", "throttled")
            raise HTTPException(429, "Too many code attempts. Please try again later.",
                                headers={"Cache-Control": "no-store", "Retry-After": "900"})
        session.execute(update(Traveler).where(Traveler.email == data.email).values(password_hash=Traveler.password_hash))
        traveler = session.exec(select(Traveler).where(Traveler.email == data.email)).first()
        challenge = session.get(PasswordResetChallenge, traveler.id) if traveler else None
        now = int(time.time())
        if (traveler is None or not traveler.password_enabled or challenge is None
                or challenge.consumed or challenge.expires_at <= now or challenge.attempts >= MAX_ATTEMPTS):
            session.rollback()
            audit(request, "reset-verify", "rejected")
            raise invalid_code()
        challenge.attempts += 1
        expected = code_digest(request.app.state.auth_settings.jwt_secret, traveler.id,
                               challenge.nonce, data.code.get_secret_value())
        matches = hmac.compare_digest(challenge.code_digest, expected)
        challenge.consumed = matches or challenge.attempts >= MAX_ATTEMPTS
        session.add(challenge)
        if not matches:
            session.commit()  # Wrong attempts must survive HTTP errors/restarts.
            audit(request, "reset-verify", "rejected")
            raise invalid_code()
        raw = secrets.token_urlsafe(32)
        session.execute(delete(PasswordResetToken).where(PasswordResetToken.traveler_id == traveler.id))
        session.add(PasswordResetToken(token_hash=token_hash(raw), traveler_id=traveler.id,
                                      expires_at=now + GRANT_SECONDS))
        session.commit()
        audit(request, "reset-verify", "success", traveler.id)
        return {"reset_token": raw, "expires_in": GRANT_SECONDS}

    @router.post("/reset-password", status_code=204)
    def reset_password(data: PasswordResetConfirm, request: Request, session: SessionDep):
        if not admitted(request, session, [("confirm-ip", client_address(request), 60, 3600)]):
            audit(request, "reset-complete", "throttled")
            raise HTTPException(429, "Too many reset attempts. Try again later.",
                                headers={"Cache-Control": "no-store", "Retry-After": "3600"})
        try:
            digest = token_hash(data.token.get_secret_value())
        except UnicodeError:
            audit(request, "reset-complete", "rejected")
            raise HTTPException(400, INVALID_MESSAGE, headers={"Cache-Control": "no-store"}) from None
        owner = select(PasswordResetToken.traveler_id).where(PasswordResetToken.token_hash == digest).scalar_subquery()
        session.execute(update(Traveler).where(Traveler.id == owner).values(password_hash=Traveler.password_hash))
        password_owner = session.exec(select(Traveler).where(Traveler.id == owner)).first()
        if password_owner is None or not password_owner.password_enabled:
            session.rollback()
            audit(request, "reset-complete", "rejected")
            raise HTTPException(400, INVALID_MESSAGE, headers={"Cache-Control": "no-store"})
        consumed = session.execute(update(PasswordResetToken).where(
            PasswordResetToken.token_hash == digest, PasswordResetToken.used.is_(False),
            PasswordResetToken.expires_at > int(time.time()),
        ).values(used=True).returning(PasswordResetToken.traveler_id)).scalar_one_or_none()
        if consumed is None:
            session.rollback()
            audit(request, "reset-complete", "rejected")
            raise HTTPException(400, INVALID_MESSAGE, headers={"Cache-Control": "no-store"})
        hashed = bcrypt.hashpw(data.password.get_secret_value().encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
        session.execute(update(Traveler).where(Traveler.id == consumed).values(password_hash=hashed))
        session.execute(update(PasswordResetToken).where(PasswordResetToken.traveler_id == consumed).values(used=True))
        session.execute(update(PasswordResetChallenge).where(PasswordResetChallenge.traveler_id == consumed).values(consumed=True))
        session.execute(update(AuthSession).where(AuthSession.traveler_id == consumed).values(revoked=True))
        # Persist the success event in the same transaction as password/session changes.
        session.add(ActivityEvent(traveler_id=consumed, event_type="password_reset", identifier="email_otp", outcome="success"))
        session.commit()
        audit(request, "reset-complete", "success", consumed)
        response = Response(status_code=204)
        clear_refresh_cookie(response, request.app.state.auth_settings)
        return response

    return router
