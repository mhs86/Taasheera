from contextlib import asynccontextmanager
import os
import shutil
from pathlib import Path
from typing import Annotated

import bcrypt
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google import genai
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, select

from .database import build_engine
from .applications.router import application_context, create_applications_router
from .activity import activity_directory_from_environment, create_activity_router, record_activity
from .admin_api import create_admin_router, install_admin_no_store
from .assistant import DEFAULT_MODEL, create_assistant_router, gemini_ask
from .auth import check_origin, create_auth_router, create_current_traveler
from .sessions import create_sessions_router
from .google_auth import create_google_auth_router
from .config import AuthSettings, RuntimeSettings
from .schema import require_current_schema
from .observability import install_private_no_store, install_request_logging
from .mailer import MailSettings, ResetSender, SesResetSender, SmtpResetSender
from .security import audit, throttle
from .password_reset import create_password_reset_router
from .models import RegisterRequest, Traveler, TravelerPublic
from .passport.router import create_passport_router
from .passport.storage import PassportImageStorage
from .profile import create_profile_router
from .document_audit import create_document_audit_router, record_document_access
from .monitoring import configure_monitoring
from .privacy import create_privacy_router, retry_erasures


def create_app(database_url: str | None = None, *, reset_sender: ResetSender | None = None) -> FastAPI:
    engine = build_engine(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.auth_settings = AuthSettings.from_environment()
        app.state.runtime_settings = RuntimeSettings.from_environment()
        app.state.activity_directory = activity_directory_from_environment()
        app.state.account_lock_directory = app.state.activity_directory.parent / ".account-locks"
        app.state.mail_settings = MailSettings.from_environment()
        app.state.reset_sender = reset_sender or (
            (SesResetSender(app.state.mail_settings) if app.state.mail_settings.provider == "ses"
             else SmtpResetSender(app.state.mail_settings)) if app.state.mail_settings else None
        )
        if app.state.runtime_settings.schema_auto_create:
            SQLModel.metadata.create_all(engine)
        else:
            require_current_schema(engine)
        retry_erasures(engine, passport_storage, app.state.activity_directory, app.state.auth_settings.jwt_secret)
        monitoring = configure_monitoring()
        try:
            yield
        finally:
            if monitoring is not None:
                monitoring.close()
            engine.dispose()

    app = FastAPI(title="Taasheera traveler API", lifespan=lifespan)
    app.state.engine = engine
    install_request_logging(app)
    install_admin_no_store(app)
    install_private_no_store(app)

    @app.get("/health/live", include_in_schema=False)
    def liveness():
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def readiness(request: Request):
        try:
            with engine.connect() as connection:
                connection.execute(sql_text("SELECT 1"))
            if not request.app.state.runtime_settings.schema_auto_create:
                require_current_schema(engine)
            if request.app.state.runtime_settings.require_tesseract and shutil.which("tesseract") is None:
                raise RuntimeError("OCR unavailable")
        except (SQLAlchemyError, RuntimeError):
            raise HTTPException(status_code=503, detail="Service is not ready.") from None
        return {"status": "ok"}

    def get_session():
        with Session(engine) as session:
            yield session

    current_traveler = create_current_traveler(get_session)
    passport_storage = PassportImageStorage(
        os.environ.get("PASSPORT_STORAGE_DIR", str(Path(__file__).resolve().parents[1] / "storage" / "passports")),
        on_access=lambda owner, upload, purpose: record_document_access(
            engine, app.state.activity_directory, owner, upload, purpose),
    )
    app.state.passport_storage = passport_storage
    app.include_router(create_activity_router(get_session, current_traveler))
    app.include_router(create_document_audit_router(get_session, current_traveler))
    app.include_router(create_privacy_router(get_session, current_traveler, passport_storage))
    app.include_router(create_auth_router(get_session, current_traveler))
    app.include_router(create_admin_router(get_session, current_traveler, passport_storage))
    app.include_router(create_sessions_router(get_session, current_traveler))
    app.include_router(create_google_auth_router(get_session, current_traveler))
    app.include_router(create_password_reset_router(get_session))
    app.include_router(create_profile_router(get_session, current_traveler))

    def current_traveler_id(traveler: Annotated[Traveler, Depends(current_traveler)]) -> int:
        return traveler.id

    def record_passport_activity(traveler_id: int, event_type: str, outcome: str):
        with Session(engine) as session:
            record_activity(session, app.state.activity_directory, traveler_id,
                            event_type, "passport", outcome)

    uploads_setting = os.environ.get("PASSPORT_UPLOADS_ENABLED", "true").lower()
    if uploads_setting not in {"true", "false"}:
        raise RuntimeError("PASSPORT_UPLOADS_ENABLED must be true or false.")
    app.include_router(create_passport_router(
        passport_storage, current_traveler_id, record_event=record_passport_activity,
        uploads_enabled=uploads_setting == "true",
    ))

    app.include_router(create_applications_router(get_session, current_traveler,
        lambda owner, upload: passport_storage.load_review(owner, upload, purpose="application_prefill"),
        load_latest_passport=lambda owner: passport_storage.latest_review(owner, purpose="application_prefill")))

    def record_assistant_activity(traveler_id: int, event_type: str, outcome: str):
        with Session(engine) as session:
            record_activity(session, app.state.activity_directory, traveler_id,
                            event_type, "assistant", outcome)

    # Without a key the assistant answers 503 and the rest of the app works as normal.
    assistant_key = os.environ.get("GEMINI_API_KEY", "").strip()
    assistant_ask = gemini_ask(
        # 20 s per attempt, 2 attempts at most: the browser gives up after 45 s.
        genai.Client(api_key=assistant_key, http_options={"timeout": 20_000, "retry_options": {"attempts": 2}}),
        os.environ.get("ASSISTANT_MODEL", DEFAULT_MODEL),
    ) if assistant_key else None

    def load_application_context(traveler_id: int, application_id: str) -> str | None:
        with Session(engine) as session:
            return application_context(session, traveler_id, application_id)

    app.include_router(create_assistant_router(
        current_traveler_id, passport_storage.latest_review, assistant_ask,
        record_event=record_assistant_activity, load_application=load_application_context,
    ))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # FastAPI's default errors can include input values, including passwords.
        errors = [
            {key: error[key] for key in ("loc", "msg", "type")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def service_error_handler(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"detail": "Service unavailable. Please try again."},
            headers={"Cache-Control": "no-store", "X-Request-ID": getattr(request.state, "request_id", "unavailable")})

    @app.post(
        "/auth/register",
        response_model=TravelerPublic,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(check_origin)],
    )
    def register(
        data: RegisterRequest,
        request: Request,
        session: Annotated[Session, Depends(get_session)],
    ) -> Traveler:
        throttle(request, session, "register", account=data.email, ip_limit=10, account_limit=3)
        email_query = select(Traveler).where(Traveler.email == data.email)
        if session.exec(email_query).first() is not None:
            audit(request, "register", "conflict")
            # No authenticated traveler owns this attempted registration.
            raise HTTPException(status_code=409, detail="Email is already registered.")

        password_hash = bcrypt.hashpw(
            data.password.get_secret_value().encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        ).decode("ascii")
        traveler = Traveler(name=data.name, email=data.email, password_hash=password_hash)
        session.add(traveler)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            # The unique constraint also catches simultaneous registrations.
            if session.exec(email_query).first() is not None:
                raise HTTPException(status_code=409, detail="Email is already registered.") from None
            raise

        session.refresh(traveler)
        audit(request, "register", "success", traveler.id)
        record_activity(session, app.state.activity_directory, traveler.id,
                        "registration", "email_password", "success")
        return traveler

    return app


app = create_app()
