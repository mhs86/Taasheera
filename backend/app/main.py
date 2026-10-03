from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Annotated

import bcrypt
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from .database import build_engine
from .activity import activity_directory_from_environment, create_activity_router, record_activity
from .auth import create_auth_router, create_current_traveler
from .google_auth import create_google_auth_router
from .config import AuthSettings
from .mailer import MailSettings, ResetSender, SmtpResetSender
from .password_reset import create_password_reset_router
from .models import RegisterRequest, Traveler, TravelerPublic
from .passport.router import create_passport_router
from .passport.storage import PassportImageStorage


def create_app(database_url: str | None = None, *, reset_sender: ResetSender | None = None) -> FastAPI:
    engine = build_engine(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.auth_settings = AuthSettings.from_environment()
        app.state.activity_directory = activity_directory_from_environment()
        app.state.mail_settings = MailSettings.from_environment()
        app.state.reset_sender = reset_sender or (
            SmtpResetSender(app.state.mail_settings) if app.state.mail_settings else None
        )
        # Development bootstrap only; use migrations once the team shares a database.
        SQLModel.metadata.create_all(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Taasheera traveler API", lifespan=lifespan)
    app.state.engine = engine

    def get_session():
        with Session(engine) as session:
            yield session

    current_traveler = create_current_traveler(get_session)
    app.include_router(create_activity_router(get_session, current_traveler))
    app.include_router(create_auth_router(get_session, current_traveler))
    app.include_router(create_google_auth_router(get_session))
    app.include_router(create_password_reset_router(get_session))
    passport_storage = PassportImageStorage(
        os.environ.get("PASSPORT_STORAGE_DIR", str(Path(__file__).resolve().parents[1] / "storage" / "passports"))
    )

    def current_traveler_id(traveler: Annotated[Traveler, Depends(current_traveler)]) -> int:
        return traveler.id

    def record_passport_activity(traveler_id: int, event_type: str, outcome: str):
        with Session(engine) as session:
            record_activity(session, app.state.activity_directory, traveler_id,
                            event_type, "passport", outcome)

    app.include_router(create_passport_router(passport_storage, current_traveler_id,
                                              record_event=record_passport_activity))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # FastAPI's default errors can include input values, including passwords.
        errors = [
            {key: error[key] for key in ("loc", "msg", "type")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.post(
        "/auth/register",
        response_model=TravelerPublic,
        status_code=status.HTTP_201_CREATED,
    )
    def register(
        data: RegisterRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> Traveler:
        email_query = select(Traveler).where(Traveler.email == data.email)
        if session.exec(email_query).first() is not None:
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
        record_activity(session, app.state.activity_directory, traveler.id,
                        "registration", "email_password", "success")
        return traveler

    return app


app = create_app()
