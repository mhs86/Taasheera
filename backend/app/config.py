import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RuntimeSettings:
    # Local development/tests may still bootstrap with create_all. Deployed
    # processes require a completed Alembic revision before accepting traffic.
    schema_auto_create: bool = False
    require_tesseract: bool = False
    environment: str = "development"

    @classmethod
    def from_environment(cls):
        values = {}
        for name, field_name in (("SCHEMA_AUTO_CREATE", "schema_auto_create"),
                                 ("REQUIRE_TESSERACT", "require_tesseract")):
            raw = os.environ.get(name, "false").lower()
            if raw not in {"true", "false"}:
                raise RuntimeError(f"{name} must be true or false.")
            values[field_name] = raw == "true"
        environment = os.environ.get("APP_ENV", "development").lower()
        if environment not in {"development", "production"}:
            raise RuntimeError("APP_ENV must be development or production.")
        if environment == "production":
            if values["schema_auto_create"]:
                raise RuntimeError("SCHEMA_AUTO_CREATE must be false in production.")
            if not os.environ.get("DATABASE_URL"):
                raise RuntimeError("DATABASE_URL must be set in production.")
            if os.environ.get("AUTH_COOKIE_SECURE", "true").lower() != "true":
                raise RuntimeError("AUTH_COOKIE_SECURE must be true in production.")
            origins = os.environ.get("AUTH_ALLOWED_ORIGINS", "")
            if not origins or any(not _https_origin(origin.strip()) for origin in origins.split(",")):
                raise RuntimeError("AUTH_ALLOWED_ORIGINS must contain exact HTTPS origins in production.")
        values["environment"] = environment
        return cls(**values)


def _https_origin(value: str) -> bool:
    if not value or any(char.isspace() for char in value) or "*" in value:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and bool(parsed.hostname) and (port is None or port > 0)
            and not parsed.path
            and not parsed.query and not parsed.fragment and not parsed.username
            and not parsed.password)


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str = field(repr=False)
    cookie_secure: bool = True
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://127.0.0.1:8000")
    access_seconds: int = 15 * 60
    refresh_seconds: int = 7 * 24 * 60 * 60
    google_client_id: str | None = None

    @classmethod
    def from_environment(cls):
        secret = os.environ.get("JWT_SECRET", "")
        if len(secret.encode("utf-8")) < 32:
            raise RuntimeError("Set JWT_SECRET to a random signing secret of at least 32 bytes.")
        secure = os.environ.get("AUTH_COOKIE_SECURE", "true").lower()
        if secure not in {"true", "false"}:
            raise RuntimeError("AUTH_COOKIE_SECURE must be true or false.")
        origins = os.environ.get(
            "AUTH_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://127.0.0.1:8000"
        )
        google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        if google_client_id and (
            not google_client_id.endswith(".apps.googleusercontent.com")
            or any(char.isspace() for char in google_client_id)
        ):
            raise RuntimeError("GOOGLE_CLIENT_ID must be a Google web application client ID.")
        return cls(
            jwt_secret=secret,
            cookie_secure=secure == "true",
            allowed_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
            google_client_id=google_client_id or None,
        )
