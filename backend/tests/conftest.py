import secrets

import pytest


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch, tmp_path):
    # Test-only secrets are generated, never read from a developer's configuration.
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("SCHEMA_AUTO_CREATE", "true")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REQUIRE_TESSERACT", "false")
    monkeypatch.setenv("ACTIVITY_LOG_DIR", str(tmp_path / "activity-logs"))
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://127.0.0.1:8000")
    # Tests never call the real Gemini API, even on a machine with a key exported.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name in ("RESET_FRONTEND_URL", "SMTP_HOST", "SMTP_FROM", "SMTP_PORT", "SMTP_SECURITY",
                 "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
