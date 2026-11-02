import secrets

import pytest
from alembic import command
from sqlalchemy import text

import migrate
from app.database import build_engine
from app.schema import migration_config


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
    monkeypatch.setenv("PASSPORT_STORAGE_DIR", str(tmp_path / "passports"))
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://127.0.0.1:8000")
    # Tests never call the real Gemini API, even on a machine with a key exported.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "SENTRY_DSN", "UPTIME_ALERT_WEBHOOK"):
        monkeypatch.delenv(name, raising=False)
    for name in ("RESET_FRONTEND_URL", "SMTP_HOST", "SMTP_FROM", "SMTP_PORT", "SMTP_SECURITY",
                 "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_TIMEOUT_SECONDS", "RESET_MAIL_PROVIDER",
                 "SES_FROM_EMAIL", "SES_REGION", "AUTH_TRUST_CLOUDFRONT_PROXY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sprint1_database(tmp_path, monkeypatch):
    """A local database as Sprint 1's create_all left it: the initial schema, no Alembic marker."""
    url = f"sqlite:///{(tmp_path / 'sprint1.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, migrate.BASELINE_REVISION)
            connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()
    return url
