"""Retryable erasure: deny access first, remove files, then delete related rows.

A failed cleanup leaves a durable work item and suspended account. Startup and
the operator retry command finish the work; a partial erasure never returns 204.
"""
import hashlib
import hmac
import logging
import shutil
from pathlib import Path
from typing import Annotated, Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from .account_lock import account_lock
from .auth import COOKIE_NAME, check_origin, clear_refresh_cookie, revoke_all_sessions, token_hash
from .google_auth import verify_google_token
from .models import (AccountErasure, ActivityEvent, AuthSession, DocumentAccess, GoogleIdentity,
                     PasswordResetChallenge, PasswordResetToken, RefreshToken, ResetRateLimit,
                     Traveler, TravelerProfile, VisaApplication)
from .security import throttle

log = logging.getLogger(__name__)


class DeleteAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE"]
    expected_traveler_id: int = Field(gt=0)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=72)
    google_id_token: SecretStr | None = Field(default=None, min_length=1, max_length=8192)


class DeleteUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE"]
    expected_user_id: int = Field(gt=0)


def remove_owner_folder(root: Path, traveler_id: int):
    folder = root / str(traveler_id)
    if folder.is_symlink():
        # Remove the link, never the destination.
        folder.unlink()
    elif folder.exists():
        shutil.rmtree(folder)


def complete_erasure(session: Session, traveler_id: int, storage, directory: Path, secret: str):
    task = session.get(AccountErasure, traveler_id)
    if task is None:
        return
    # Synchronize with login, password reset and operator updates as well as owner requests.
    session.execute(update(Traveler).where(Traveler.id == traveler_id).values(status="suspended"))
    traveler = session.get(Traveler, traveler_id)
    remove_owner_folder(storage.root, traveler_id)
    remove_owner_folder(directory, traveler_id)
    session_ids = select(AuthSession.id).where(AuthSession.traveler_id == traveler_id)
    session.execute(delete(RefreshToken).where(RefreshToken.session_id.in_(session_ids)))
    for model in (AuthSession, GoogleIdentity, PasswordResetChallenge, PasswordResetToken,
                  TravelerProfile, VisaApplication, ActivityEvent):
        session.execute(delete(model).where(model.traveler_id == traveler_id))
    session.execute(delete(DocumentAccess).where(or_(DocumentAccess.traveler_id == traveler_id,
                                                   DocumentAccess.actor_id == traveler_id)))
    # Remove account-specific admission keys. Shared IP limits expire after 15 minutes.
    if traveler is not None:
        digests = [hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
                   for value in (traveler.email, str(traveler_id))]
        for digest in digests:
            session.execute(delete(ResetRateLimit).where(ResetRateLimit.key.endswith(f"-account:{digest}")))
    session.execute(delete(AccountErasure).where(AccountErasure.traveler_id == traveler_id))
    session.execute(delete(Traveler).where(Traveler.id == traveler_id))
    session.commit()


def erase_account(session, traveler, storage, directory, secret) -> bool:
    traveler.status = "suspended"
    session.add(traveler)
    revoke_all_sessions(session, traveler.id)
    if session.get(AccountErasure, traveler.id) is None:
        session.add(AccountErasure(traveler_id=traveler.id))
    session.commit()  # Durable intent before filesystem changes; all tokens stop working now.
    try:
        complete_erasure(session, traveler.id, storage, directory, secret)
        return True
    except (OSError, SQLAlchemyError):
        session.rollback()
        log.error("Account erasure pending; operator retry required")
        return False


def retry_erasures(engine, storage, directory, secret) -> int:
    with Session(engine) as session:
        ids = list(session.exec(select(AccountErasure.traveler_id)).all())
    pending = 0
    for owner_id in ids:
        try:
            with account_lock(directory.parent / ".account-locks", owner_id), Session(engine) as session:
                complete_erasure(session, owner_id, storage, directory, secret)
        except (OSError, SQLAlchemyError, HTTPException):
            pending += 1
            log.error("Account erasure retry pending")
    return pending


def erasure_response(complete: bool) -> Response:
    from fastapi.responses import JSONResponse
    return (Response(status_code=204, headers={"Cache-Control": "no-store"}) if complete else
            JSONResponse({"status": "pending", "message": "Account disabled. Data erasure is queued for retry."},
                         status_code=202, headers={"Cache-Control": "no-store"}))


def create_privacy_router(get_session, current_traveler, storage):
    router = APIRouter(prefix="/auth", tags=["Account erasure"])

    @router.delete("/account", status_code=204, response_class=Response,
                   responses={202: {"description": "Account disabled; data erasure queued for retry"}},
                   dependencies=[Depends(check_origin)])
    def delete_account(data: DeleteAccount, request: Request,
                       session: Annotated[Session, Depends(get_session)],
                       traveler: Annotated[Traveler, Depends(current_traveler)]):
        if data.expected_traveler_id != traveler.id:
            raise HTTPException(409, "Your signed-in account changed. Reload before deleting.")
        raw = request.cookies.get(COOKIE_NAME)
        cookie_token = session.get(RefreshToken, token_hash(raw)) if raw else None
        cookie_session = session.get(AuthSession, cookie_token.session_id) if cookie_token else None
        if cookie_session is not None and cookie_session.traveler_id != traveler.id:
            raise HTTPException(409, "Your signed-in account changed. Reload before deleting.")
        throttle(request, session, "delete-account", account=str(traveler.id), account_limit=5)
        # Do provider HTTP before the row lock; compare its subject with the saved identity.
        if not traveler.password_enabled:
            client_id = request.app.state.auth_settings.google_client_id
            if not client_id or data.google_id_token is None:
                raise HTTPException(403, "Confirm your Google identity before deleting your account.")
            claims = verify_google_token(data.google_id_token.get_secret_value(), client_id)
            identity = session.get(GoogleIdentity, claims["sub"])
            if identity is None or identity.traveler_id != traveler.id:
                raise HTTPException(403, "Confirm the Google identity connected to this account.")
        session.execute(update(Traveler).where(Traveler.id == traveler.id).values(status=Traveler.status))
        session.refresh(traveler)
        if traveler.role == "admin":
            raise HTTPException(409, "Transfer your admin role before deleting your account.")
        if traveler.password_enabled:
            try:
                matches = data.password is not None and bcrypt.checkpw(
                    data.password.get_secret_value().encode(), traveler.password_hash.encode("ascii"))
            except (ValueError, UnicodeError):
                matches = False
            if not matches:
                raise HTTPException(403, "Current password is incorrect.")
        result = erasure_response(erase_account(session, traveler, storage, request.app.state.activity_directory,
                                               request.app.state.auth_settings.jwt_secret))
        clear_refresh_cookie(result, request.app.state.auth_settings)
        return result

    return router
