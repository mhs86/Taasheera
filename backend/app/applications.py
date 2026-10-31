"""Small application registry; only backend workflow code may advance status."""
from typing import Annotated
from uuid import uuid4
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, Field
from sqlmodel import Session, select

from .activity import record_activity
from .auth import check_origin
from .models import ApplicationStatus, Traveler, VisaApplication

CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}$")]


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: CountryCode
    nationality: CountryCode
    visa_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ApplicationPublic(ApplicationCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: str
    status: ApplicationStatus
    created_at: datetime


class ApplicationSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=100)


def create_applications_router(get_session, current_traveler):
    router = APIRouter(prefix="/applications", tags=["Applications"])
    SessionDep = Annotated[Session, Depends(get_session)]
    Owner = Annotated[Traveler, Depends(current_traveler)]

    @router.get("", response_model=list[ApplicationPublic])
    def list_applications(search: Annotated[ApplicationSearch, Query()], session: SessionDep,
                          traveler: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return session.exec(select(VisaApplication).where(VisaApplication.traveler_id == traveler.id)
            .order_by(VisaApplication.created_at.desc(), VisaApplication.id.desc())
            .offset((search.page - 1) * search.page_size).limit(search.page_size)).all()

    @router.get("/{application_id}", response_model=ApplicationPublic)
    def get_application(application_id: str, session: SessionDep, traveler: Owner, response: Response):
        application = session.get(VisaApplication, application_id)
        if application is None or application.traveler_id != traveler.id:
            raise HTTPException(404, "Application not found.")
        response.headers["Cache-Control"] = "no-store"
        return application

    @router.post("", response_model=ApplicationPublic, status_code=201, dependencies=[Depends(check_origin)])
    def create_application(data: ApplicationCreate, session: SessionDep, traveler: Owner,
                           request: Request, response: Response):
        application = VisaApplication(id=uuid4().hex, traveler_id=traveler.id, **data.model_dump())
        session.add(application)
        record_activity(session, request.app.state.activity_directory, traveler.id,
                        "application_created", "application", "success")
        response.headers["Cache-Control"] = "no-store"
        return application

    return router
