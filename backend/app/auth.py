import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
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
from .activity import record_activity
from .models import AccessTokenPublic, AuthSession, ChangePasswordRequest, LoginRequest, RefreshToken, Traveler, TravelerPublic
from .security import audit, throttle


COOKIE_NAME = "taasheera_refresh"
ISSUER = "taasheera"
AUDIENCE = "taasheera-traveler"
bearer = HTTPBearer(auto_error=False)
# Unknown emails still perform the same bcrypt work as incorrect passwords.
DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds=12))
# A code, because /auth/login also answers 403 to a disallowed Origin.
SUSPENDED = {"code": "account_suspended", "message": "This account is suspended."}


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def device_label(user_agent: str | None) -> str:
    """Recognize a few common browser/OS families without retaining the header."""
    agent = (user_agent or "").lower()
    browser = next((name for marker, name in (
        ("edg/", "Edge"), ("opr/", "Opera"), ("firefox/", "Firefox"),
        ("chrome/", "Chrome"), ("safari/", "Safari"),
    ) if marker in agent), None)
    system = next((name for marker, name in (
        ("windows", "Windows"), ("android", "Android"),
        ("iphone", "iPhone"), ("ipad", "iPad"), ("mac os", "macOS"),
        ("linux", "Linux"),
    ) if marker in agent), None)
    return f"{browser} on {system}" if browser and system else "Unknown device"


def revoke_other_sessions(session: Session, traveler_id: int, current_session_id: str) -> int:
    """Mark a traveler's other sessions revoked within the caller's transaction."""
    result = session.execute(update(AuthSession).where(
        AuthSession.traveler_id == traveler_id,
        AuthSession.id != current_session_id,
        AuthSession.revoked.is_(False),
    ).values(revoked=True))
    return result.rowcount


def revoke_all_sessions(session: Session, traveler_id: int) -> int:
    """Mark every session of a traveler revoked within the caller's transaction."""
    result = session.execute(update(AuthSession).where(
        AuthSession.traveler_id == traveler_id, AuthSession.revoked.is_(False),
    ).values(revoked=True))
    return result.rowcount


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


def start_session(traveler: Traveler, request: Request, response: Response, session: Session,
                  *, method: str = "email_password"):
    """Common session issuance for password and verified Google sign-in."""
    settings = request.app.state.auth_settings
    # Callers check the credential first, so only its owner learns the account is suspended.
    # They also lock the traveler row, so a suspension cannot commit between this check and the new session.
    if traveler.status != "active":
        audit(request, "login" if method == "email_password" else "google-login", "suspended", traveler.id)
        record_activity(session, request.app.state.activity_directory, traveler.id, "sign_in", method, "suspended")
        raise HTTPException(403, SUSPENDED, headers={"Cache-Control": "no-store"})
    traveler.last_login_method = method
    traveler.last_login_at = int(time.time())
    session.add(traveler)
    previous = request.cookies.get(COOKIE_NAME)
    if previous:
        old = session.get(RefreshToken, token_hash(previous))
        if old:
            session.execute(update(AuthSession).where(AuthSession.id == old.session_id).values(revoked=True))
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    auth_session = AuthSession(
        id=str(uuid4()), traveler_id=traveler.id, refresh_hash=token_hash(raw),
        expires_at=int(time.time()) + settings.refresh_seconds,
        device_label=device_label(request.headers.get("user-agent")),
        created_at=now, last_active_at=now,
    )
    session.add(auth_session)
    session.flush()
    session.add(RefreshToken(token_hash=auth_session.refresh_hash, session_id=auth_session.id))
    session.commit()
    set_refresh_cookie(response, raw, auth_session, settings)
    return access_token(auth_session, settings)


def create_current_traveler(get_session):
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
            # Suspension also revokes sessions; this covers a status changed outside the admin API.
            if traveler is None or traveler.status != "active":
                raise unauthorized
            request.state.auth_session_id = auth_session.id
            return traveler
        except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
            raise unauthorized from None

    return current_traveler


def create_auth_router(get_session, current_traveler=None):
    router = APIRouter(prefix="/auth", tags=["Authentication"])
    SessionDep = Annotated[Session, Depends(get_session)]
    current_traveler = current_traveler or create_current_traveler(get_session)

    @router.post("/login", response_model=AccessTokenPublic, dependencies=[Depends(check_origin)])
    def login(data: LoginRequest, request: Request, response: Response, session: SessionDep):
        throttle(request, session, "login", account=data.email)
        # Serialize login with password reset so an old-password login cannot
        # create a new session after reset has revoked existing sessions.
        session.execute(update(Traveler).where(Traveler.email == data.email).values(password_hash=Traveler.password_hash))
        traveler = session.exec(select(Traveler).where(Traveler.email == data.email)).first()
        password_enabled = traveler is not None and traveler.password_enabled
        stored_hash = traveler.password_hash.encode("ascii") if password_enabled else DUMMY_HASH
        try:
            password = data.password.get_secret_value().encode("utf-8")
            # bcrypt rejects overlong input; still do bcrypt work before rejecting it.
            valid_length = len(password) <= 72
            matches = bcrypt.checkpw(password if valid_length else b"invalid-password", stored_hash)
        except (ValueError, UnicodeError):
            matches = False
            valid_length = False
        if not password_enabled or not valid_length or not matches:
            audit(request, "login", "rejected", traveler.id if traveler else None)
            if traveler is not None:
                record_activity(session, request.app.state.activity_directory, traveler.id,
                                "sign_in", "email_password", "failure")
            raise HTTPException(
                status_code=401, detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )

        result = start_session(traveler, request, response, session)
        audit(request, "login", "success", traveler.id)
        record_activity(session, request.app.state.activity_directory, traveler.id,
                        "sign_in", "email_password", "success")
        return result

    @router.get("/me", response_model=TravelerPublic)
    def me(response: Response, traveler: Annotated[Traveler, Depends(current_traveler)]):
        response.headers["Cache-Control"] = "no-store"
        return traveler

    @router.post("/change-password", status_code=204, dependencies=[Depends(check_origin)])
    def change_password(data: ChangePasswordRequest, request: Request, session: SessionDep,
                        traveler: Annotated[Traveler, Depends(current_traveler)]):
        throttle(request, session, "change-password", account=str(traveler.id), account_limit=5)
        # Serialize with password reset and password login before checking the hash.
        session.execute(update(Traveler).where(Traveler.id == traveler.id)
                        .values(password_hash=Traveler.password_hash))
        session.refresh(traveler)
        if not traveler.password_enabled:
            audit(request, "change-password", "unavailable", traveler.id)
            raise HTTPException(403, "Password change is unavailable for Google-only accounts.",
                                headers={"Cache-Control": "no-store"})
        try:
            current = data.current_password.get_secret_value().encode("utf-8")
            matches = bcrypt.checkpw(current, traveler.password_hash.encode("ascii"))
        except (ValueError, UnicodeError):
            matches = False
        if not matches:
            audit(request, "change-password", "rejected", traveler.id)
            raise HTTPException(403, "Current password is incorrect.",
                                headers={"Cache-Control": "no-store"})
        new_password = data.password.get_secret_value().encode("utf-8")
        if new_password == current:
            raise HTTPException(400, "Choose a different new password.",
                                headers={"Cache-Control": "no-store"})
        traveler.password_hash = bcrypt.hashpw(new_password, bcrypt.gensalt(rounds=12)).decode("ascii")
        session.add(traveler)
        revoke_other_sessions(session, traveler.id, request.state.auth_session_id)
        session.commit()
        audit(request, "change-password", "success", traveler.id)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

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

        # last_active_at only moves on refresh, so this is the time since the last refresh.
        # Sessions created before it was recorded have none and are not limited.
        last_active = auth_session.last_active_at
        if last_active is not None:
            if last_active.tzinfo is None:  # SQLite drops timezone information when reading back.
                last_active = last_active.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last_active > timedelta(seconds=settings.idle_seconds):
                session.execute(update(AuthSession).where(AuthSession.id == auth_session.id).values(revoked=True))
                session.commit()
                audit(request, "refresh", "idle_expired", auth_session.traveler_id)
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
            ).values(refresh_hash=new_hash, last_active_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False)
        )
        traveler = session.get(Traveler, auth_session.traveler_id)
        if result.rowcount != 1 or traveler is None or traveler.status != "active":
            # A replay revokes the current replacement token as well, and a suspended account's session ends.
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
            auth_session = session.get(AuthSession, old.session_id)
            session.execute(update(AuthSession).where(AuthSession.id == old.session_id).values(revoked=True))
            session.commit()
            if auth_session is not None:
                record_activity(session, request.app.state.activity_directory,
                                auth_session.traveler_id, "logout", "session", "success")
        response = Response(status_code=204)
        clear_refresh_cookie(response, request.app.state.auth_settings)
        return response

    return router
