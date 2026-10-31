from datetime import date, datetime, timezone
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, StringConstraints, field_validator
from pydantic import Field as SchemaField
from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint, Text


# Stored as plain strings guarded by named CHECK constraints (portable; no database enum types).
Role = Literal["traveler", "support", "admin"]
Status = Literal["active", "suspended"]
ROLES: tuple[str, ...] = get_args(Role)
STATUSES: tuple[str, ...] = get_args(Status)


class Traveler(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "(auth_type = 'google' AND password_hash = '') OR "
            "(auth_type = 'email_password' AND password_hash <> '')",
            name="ck_traveler_auth_type",
        ),
        CheckConstraint("role IN ('traveler', 'support', 'admin')", name="ck_traveler_role"),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_traveler_status"),
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    email: str = Field(max_length=254, unique=True, index=True)
    # Latest verified Google email; identities authenticate by Google subject.
    sso_email: str | None = Field(default=None, max_length=254, index=True)
    # Empty means password authentication is disabled (Google-only account).
    # Preserve the existing NOT NULL column for compatibility with local DBs.
    password_hash: str = Field(max_length=60, repr=False)
    auth_type: str = Field(default="email_password", max_length=20, index=True)
    last_login_method: str | None = Field(default=None, max_length=20)
    last_login_at: int | None = None
    # Never taken from a request body: sign-up always creates an active traveler.
    # Only manage.py set-role (and, later, admins) change these.
    role: str = Field(default="traveler", max_length=20, sa_column_kwargs={"server_default": "traveler"})
    status: str = Field(default="active", max_length=20, sa_column_kwargs={"server_default": "active"})
    # Sign-up time; None for accounts made before it was recorded.
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def password_enabled(self) -> bool:
        return self.auth_type == "email_password" and bool(self.password_hash)


class TravelerProfile(SQLModel, table=True):
    traveler_id: int = Field(primary_key=True, foreign_key="traveler.id")
    surname: str | None = Field(default=None, max_length=100, repr=False)
    given_names: str | None = Field(default=None, max_length=100, repr=False)
    birth_date: date | None = Field(default=None, repr=False)
    nationality: str | None = Field(default=None, max_length=3, repr=False)
    phone: str | None = Field(default=None, max_length=16, repr=False)
    address_line1: str | None = Field(default=None, sa_type=Text, repr=False)
    address_line2: str | None = Field(default=None, sa_type=Text, repr=False)
    address_city: str | None = Field(default=None, sa_type=Text, repr=False)
    address_region: str | None = Field(default=None, sa_type=Text, repr=False)
    address_postal_code: str | None = Field(default=None, sa_type=Text, repr=False)
    address_country: str | None = Field(default=None, max_length=3, repr=False)


class ActivityEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    traveler_id: int = Field(foreign_key="traveler.id", index=True)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    event_type: str = Field(max_length=40, index=True)
    identifier: str = Field(max_length=80)
    outcome: str = Field(max_length=20)


class GoogleIdentity(SQLModel, table=True):
    subject: str = Field(primary_key=True, max_length=255)
    traveler_id: int = Field(foreign_key="traveler.id", unique=True, index=True)


class GoogleLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_token: SecretStr = SchemaField(min_length=1, max_length=8192)


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


class GoogleLinkRequest(PasswordInput):
    model_config = ConfigDict(extra="forbid")
    id_token: SecretStr = SchemaField(min_length=1, max_length=8192)
    expected_traveler_id: int = SchemaField(gt=0)


class ChangePasswordRequest(PasswordInput):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = SchemaField(min_length=1, max_length=72)
    # Inherit PasswordInput's length and UTF-8 byte validation for the new password.
    password: SecretStr = SchemaField(alias="new_password", min_length=8, max_length=72)


class AuthConfigurationPublic(BaseModel):
    google_client_id: str | None


class TravelerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    sso_email: str | None = None
    auth_type: Literal["email_password", "google"] = "email_password"
    password_enabled: bool = True
    last_login_method: str | None = None


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
    device_label: str | None = Field(default=None, max_length=100)
    created_at: datetime | None = None
    last_active_at: datetime | None = None


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


class PasswordResetVerify(PasswordResetRequest):
    code: SecretStr = SchemaField(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def ascii_digits(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().isascii() or not value.get_secret_value().isdigit():
            raise ValueError("Enter the six-digit code from your email.")
        return value


class PasswordResetGrant(BaseModel):
    reset_token: str
    expires_in: int


class PasswordResetChallenge(SQLModel, table=True):
    traveler_id: int = Field(primary_key=True, foreign_key="traveler.id")
    nonce: str = Field(max_length=64, repr=False)
    code_digest: str = Field(max_length=64, repr=False)
    expires_at: int = Field(index=True)
    attempts: int = 0
    consumed: bool = False


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


ApplicationStatus = Literal["DRAFT", "IN_PROGRESS", "READY", "SUBMITTED", "DECIDED", "FAILED"]
APPLICATION_STATUSES = get_args(ApplicationStatus)


class VisaApplication(SQLModel, table=True):
    __table_args__ = (CheckConstraint(
        "status IN ('DRAFT','IN_PROGRESS','READY','SUBMITTED','DECIDED','FAILED')",
        name="ck_visaapplication_status"),)
    id: str = Field(primary_key=True, max_length=32)
    traveler_id: int = Field(foreign_key="traveler.id", index=True)
    destination: str = Field(max_length=3)
    nationality: str = Field(max_length=3)
    visa_type: str = Field(max_length=80)
    status: str = Field(default="DRAFT", max_length=20, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentAccess(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    traveler_id: int = Field(foreign_key="traveler.id", index=True)
    actor_id: int = Field(foreign_key="traveler.id", index=True)
    upload_id: str = Field(max_length=32)
    purpose: str = Field(max_length=30)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)


class AccountErasure(SQLModel, table=True):
    # Durable work item: failed file/database cleanup is retried, never reported as complete.
    traveler_id: int = Field(primary_key=True, foreign_key="traveler.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
