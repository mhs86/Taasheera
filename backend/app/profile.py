"""Traveler-owned profile fields and their API."""

from datetime import date
import re
from typing import Annotated

import phonenumbers
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session

from .models import Traveler, TravelerProfile


class ProfileFields(BaseModel):
    """Shared profile contract for the account page and intake chat."""

    model_config = ConfigDict(extra="forbid")

    surname: str | None = Field(default=None, min_length=1, max_length=100)
    given_names: str | None = Field(default=None, max_length=100)
    birth_date: date | None = None
    nationality: str | None = Field(default=None, pattern=r"^[A-Z]{1,3}$")
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_city: str | None = None
    address_region: str | None = None
    address_postal_code: str | None = None
    address_country: str | None = Field(default=None, pattern=r"^[A-Z]{1,3}$")

    @field_validator("birth_date", mode="before")
    @classmethod
    def iso_birth_date(cls, value):
        if isinstance(value, date):
            return value
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)):
            raise ValueError("Birth date must use YYYY-MM-DD.")
        return value

    @field_validator("birth_date")
    @classmethod
    def past_birth_date(cls, value: date | None) -> date | None:
        if value is not None and value >= date.today():
            raise ValueError("Birth date must be in the past.")
        return value

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, value):
        if value is None or value == "":
            return None
        if not isinstance(value, str) or not value.startswith("+"):
            raise ValueError("Phone must be an international E.164 number.")
        try:
            number = phonenumbers.parse(value, None)
        except phonenumbers.NumberParseException:
            raise ValueError("Phone must be a valid international number.") from None
        if not phonenumbers.is_valid_number(number):
            raise ValueError("Phone must be a valid international number.")
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def create_profile_router(get_session, current_traveler) -> APIRouter:
    from .auth import check_origin

    router = APIRouter(prefix="/profile", tags=["profile"])
    SessionDep = Annotated[Session, Depends(get_session)]
    TravelerDep = Annotated[Traveler, Depends(current_traveler)]

    @router.get("", response_model=ProfileFields)
    def get_profile(traveler: TravelerDep, session: SessionDep, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        profile = session.get(TravelerProfile, traveler.id)
        return ProfileFields.model_validate(profile, from_attributes=True) if profile else ProfileFields()

    @router.put("", response_model=ProfileFields, dependencies=[Depends(check_origin)])
    def replace_profile(fields: ProfileFields, traveler: TravelerDep, session: SessionDep, response: Response):
        profile = session.get(TravelerProfile, traveler.id)
        if profile is None:
            profile = TravelerProfile(traveler_id=traveler.id)
        for name, value in fields.model_dump().items():
            setattr(profile, name, value)
        session.add(profile)
        session.commit()
        response.headers["Cache-Control"] = "private, no-store"
        return fields

    return router
