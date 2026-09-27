import secrets
import time
from typing import Annotated
from urllib.parse import urlencode

import bcrypt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .auth import check_origin, clear_refresh_cookie, token_hash
from .models import AuthSession, PasswordResetConfirm, PasswordResetRequest, PasswordResetToken, ResetRateLimit, Traveler


REQUEST_MESSAGE = {"detail": "If an account exists for that email, a password reset email will be sent."}
INVALID_MESSAGE = "Invalid or expired password reset token."


def consume_limit(session: Session, scope: str, value: str, limit: int, seconds: int, now: int) -> bool:
    key = f"{scope}:{token_hash(value)}"
    # The UPDATE and unique key make admission safe across threads/processes.
    session.execute(delete(ResetRateLimit).where(ResetRateLimit.expires_at <= now))
    result = session.execute(update(ResetRateLimit).where(
        ResetRateLimit.key == key, ResetRateLimit.count < limit,
    ).values(count=ResetRateLimit.count + 1))
    if result.rowcount:
        return True
    try:
        with session.begin_nested():
            session.add(ResetRateLimit(key=key, expires_at=now + seconds))
            session.flush()
        return True
    except IntegrityError:
        # Either the bucket is full or another transaction inserted it first.
        result = session.execute(update(ResetRateLimit).where(
            ResetRateLimit.key == key, ResetRateLimit.count < limit,
        ).values(count=ResetRateLimit.count + 1))
        return result.rowcount == 1


def deliver_reset(app, recipient: str, raw: str, digest: str):
    link = f"{app.state.mail_settings.frontend_url}#{urlencode({'token': raw})}"
    try:
        app.state.reset_sender.send_reset(recipient, link)
        return
    except Exception:
        # Exceptions from providers can contain the whole message. Never log them.
        pass
    # Outside the exception handler: a DB failure must not chain/log the provider
    # exception. A failed/uncertain delivery cannot leave a usable link behind.
    with Session(app.state.engine) as session:
        session.execute(delete(PasswordResetToken).where(PasswordResetToken.token_hash == digest))
        session.commit()


def create_password_reset_router(get_session):
    router = APIRouter(prefix="/auth", tags=["Password reset"], dependencies=[Depends(check_origin)])
    SessionDep = Annotated[Session, Depends(get_session)]

    @router.post("/forgot-password", status_code=202)
    def request_reset(data: PasswordResetRequest, request: Request, response: Response,
                      background: BackgroundTasks, session: SessionDep):
        response.headers["Cache-Control"] = "no-store"
        if request.app.state.mail_settings is None:
            raise HTTPException(503, "Password reset is not configured.", headers={"Cache-Control": "no-store"})
        now = int(time.time())
        ip = request.client.host if request.client else "unknown"
        admitted = consume_limit(session, "request-ip", ip, 20, 3600, now)
        if admitted:
            admitted = consume_limit(session, "email-hour", data.email, 5, 3600, now)
        if admitted:
            admitted = consume_limit(session, "email-minute", data.email, 1, 60, now)
        session.commit()
        if not admitted:
            return REQUEST_MESSAGE

        # A write lock on the traveler serializes issuance with reset completion.
        session.execute(update(Traveler).where(Traveler.email == data.email).values(password_hash=Traveler.password_hash))
        traveler = session.exec(select(Traveler).where(Traveler.email == data.email)).first()
        if traveler is not None and traveler.password_hash:
            raw = secrets.token_urlsafe(32)
            digest = token_hash(raw)
            session.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at <= now))
            session.add(PasswordResetToken(token_hash=digest, traveler_id=traveler.id, expires_at=now + 1800))
            session.commit()
            background.add_task(deliver_reset, request.app, traveler.email, raw, digest)
        else:
            session.commit()
        return REQUEST_MESSAGE

    @router.post("/reset-password", status_code=204)
    def reset_password(data: PasswordResetConfirm, request: Request, session: SessionDep):
        now = int(time.time())
        ip = request.client.host if request.client else "unknown"
        admitted = consume_limit(session, "confirm-ip", ip, 60, 3600, now)
        session.commit()
        if not admitted:
            raise HTTPException(429, "Too many reset attempts. Try again later.",
                                headers={"Cache-Control": "no-store", "Retry-After": "3600"})
        try:
            digest = token_hash(data.token.get_secret_value())
        except UnicodeError:
            raise HTTPException(400, INVALID_MESSAGE, headers={"Cache-Control": "no-store"}) from None
        # Lock the account first, including when different outstanding links race.
        owner = select(PasswordResetToken.traveler_id).where(PasswordResetToken.token_hash == digest).scalar_subquery()
        session.execute(update(Traveler).where(Traveler.id == owner).values(password_hash=Traveler.password_hash))
        password_owner = session.exec(select(Traveler).where(Traveler.id == owner)).first()
        if password_owner is None or not password_owner.password_hash:
            session.rollback()
            raise HTTPException(400, INVALID_MESSAGE, headers={"Cache-Control": "no-store"})
        consumed = session.execute(update(PasswordResetToken).where(
            PasswordResetToken.token_hash == digest,
            PasswordResetToken.used.is_(False),
            PasswordResetToken.expires_at > int(time.time()),
        ).values(used=True).returning(PasswordResetToken.traveler_id)).scalar_one_or_none()
        if consumed is None:
            session.rollback()
            raise HTTPException(400, INVALID_MESSAGE, headers={"Cache-Control": "no-store"})
        password_hash = bcrypt.hashpw(data.password.get_secret_value().encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
        session.execute(update(Traveler).where(Traveler.id == consumed).values(password_hash=password_hash))
        session.execute(update(PasswordResetToken).where(PasswordResetToken.traveler_id == consumed).values(used=True))
        session.execute(update(AuthSession).where(AuthSession.traveler_id == consumed).values(revoked=True))
        session.commit()
        response = Response(status_code=204)
        clear_refresh_cookie(response, request.app.state.auth_settings)
        return response

    return router
