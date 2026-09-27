import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str = field(repr=False)
    cookie_secure: bool = True
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://127.0.0.1:8000")
    access_seconds: int = 15 * 60
    refresh_seconds: int = 7 * 24 * 60 * 60

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
        return cls(
            jwt_secret=secret,
            cookie_secure=secure == "true",
            allowed_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        )
