"""Local-only setup and server launcher; production uses environment settings."""

import os
import secrets
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PUBLIC_CONFIG = BACKEND_DIR / ".env.development"
PRIVATE_CONFIG = BACKEND_DIR / ".env.local"


def read_setting(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise SystemExit(f"Missing {path.name}. Run 'py dev.py setup' if this is the private JWT file.") from None
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and name.strip() == key and value.strip():
            return value.strip()
    raise SystemExit(f"Missing {key} in {path.name}.")


def read_optional_setting(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and name.strip() == key and value.strip():
            return value.strip()
    return None


def setup() -> None:
    try:
        descriptor = os.open(PRIVATE_CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"{PRIVATE_CONFIG.name} already exists; leaving its JWT secret unchanged.")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as local_file:
        local_file.write(f"JWT_SECRET={secrets.token_urlsafe(48)}\n")
    print(f"Created Git-ignored {PRIVATE_CONFIG.name}. The JWT secret was not printed.")


def configure_environment() -> None:
    os.environ.setdefault("JWT_SECRET", read_setting(PRIVATE_CONFIG, "JWT_SECRET"))
    os.environ.setdefault("GOOGLE_CLIENT_ID", read_setting(PUBLIC_CONFIG, "GOOGLE_CLIENT_ID"))
    os.environ.setdefault("AUTH_COOKIE_SECURE", "false")  # Loopback HTTP only.
    os.environ.setdefault("SCHEMA_AUTO_CREATE", "true")  # Existing local DBs remain usable.
    # Optional: the passport assistant's key, kept in the Git-ignored file like the JWT secret.
    # Without it the assistant answers "unavailable" and everything else still works.
    gemini_key = read_optional_setting(PRIVATE_CONFIG, "GEMINI_API_KEY")
    if gemini_key:
        os.environ.setdefault("GEMINI_API_KEY", gemini_key)


if __name__ == "__main__":
    if sys.argv[1:] == ["setup"]:
        setup()
    elif sys.argv[1:] == ["run"]:
        configure_environment()
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, access_log=False)
    else:
        raise SystemExit("Usage: python dev.py setup | run")
