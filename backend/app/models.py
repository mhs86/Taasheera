from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, StringConstraints, field_validator
from pydantic import Field as SchemaField
from sqlmodel import Field, SQLModel


class Traveler(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    email: str = Field(max_length=254, unique=True, index=True)
    password_hash: str = Field(max_length=60, repr=False)


class PasswordInput(BaseModel):
    password: SecretStr = SchemaField(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: SecretStr) -> SecretStr:
        try:
            encoded = value.get_secret_value().encode("utf-8")
        except UnicodeError:
            raise ValueError("Password must contain valid Unicode characters") from None
        if len(encoded) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class RegisterRequest(PasswordInput):
    # This endpoint only creates travelers; callers cannot supply roles or IDs.
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: EmailStr = SchemaField(max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class TravelerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class AccessTokenPublic(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class AuthSession(SQLModel, table=True):
    id: str = Field(primary_key=True)
    traveler_id: int = Field(foreign_key="traveler.id", index=True)
    refresh_hash: str = Field(max_length=64, repr=False)
    expires_at: int
    revoked: bool = False


class RefreshToken(SQLModel, table=True):
    # Retain past hashes until session cleanup so replay revokes the whole session.
    token_hash: str = Field(primary_key=True, max_length=64, repr=False)
    session_id: str = Field(foreign_key="authsession.id", index=True)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = SchemaField(max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class PasswordResetConfirm(PasswordInput):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = SchemaField(min_length=1, max_length=128)


class PasswordResetToken(SQLModel, table=True):
    token_hash: str = Field(primary_key=True, max_length=64, repr=False)
    traveler_id: int = Field(foreign_key="traveler.id", index=True)
    expires_at: int = Field(index=True)
    used: bool = False


class ResetRateLimit(SQLModel, table=True):
    # Scope + SHA-256 of the normalized email or client IP; no raw identifiers.
    key: str = Field(primary_key=True, max_length=100)
    expires_at: int = Field(index=True)
    count: int = 1
