import secrets

import pytest


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch):
    # Test-only secrets are generated, never read from a developer's configuration.
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://127.0.0.1:8000")
    for name in ("RESET_FRONTEND_URL", "SMTP_HOST", "SMTP_FROM", "SMTP_PORT", "SMTP_SECURITY",
                 "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
