from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, StringConstraints, field_validator
from pydantic import Field as SchemaField
from sqlmodel import Field, SQLModel


class Traveler(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    email: str = Field(max_length=254, unique=True, index=True)
    password_hash: str = Field(max_length=60, repr=False)


class RegisterRequest(BaseModel):
    # This endpoint only creates travelers; callers cannot supply roles or IDs.
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: EmailStr = SchemaField(max_length=254)
    password: SecretStr = SchemaField(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class TravelerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
