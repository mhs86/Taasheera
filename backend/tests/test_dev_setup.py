import pytest
import uvicorn
from sqlalchemy import inspect

import dev
import migrate
from app.config import AuthSettings
from app.database import build_engine
from app.schema import schema_revision


def test_setup_creates_private_secret_once_without_printing_it(tmp_path, monkeypatch, capsys):
    private = tmp_path / ".env.local"
    monkeypatch.setattr(dev, "PRIVATE_CONFIG", private)

    dev.setup()
    first = dev.read_setting(private, "JWT_SECRET")
    assert len(first.encode("utf-8")) >= 32
    assert first not in capsys.readouterr().out

    dev.setup()
    assert dev.read_setting(private, "JWT_SECRET") == first


def test_dev_launcher_loads_files_and_preserves_explicit_environment(tmp_path, monkeypatch):
    private = tmp_path / ".env.local"
    public = tmp_path / ".env.development"
    private.write_text("JWT_SECRET=" + "s" * 48 + "\n", encoding="utf-8")
    public.write_text("GOOGLE_CLIENT_ID=dev-client.apps.googleusercontent.com\n", encoding="utf-8")
    monkeypatch.setattr(dev, "PRIVATE_CONFIG", private)
    monkeypatch.setattr(dev, "PUBLIC_CONFIG", public)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("SCHEMA_AUTO_CREATE", raising=False)

    dev.configure_environment()
    settings = AuthSettings.from_environment()
    assert settings.jwt_secret == "s" * 48
    assert settings.google_client_id == "dev-client.apps.googleusercontent.com"
    assert settings.cookie_secure is False
    assert dev.os.environ["SCHEMA_AUTO_CREATE"] == "false"

    monkeypatch.setenv("JWT_SECRET", "p" * 48)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "override.apps.googleusercontent.com")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    dev.configure_environment()
    settings = AuthSettings.from_environment()
    assert settings.jwt_secret == "p" * 48
    assert settings.google_client_id == "override.apps.googleusercontent.com"
    assert settings.cookie_secure is True


def test_dev_launcher_loads_the_optional_assistant_key(tmp_path, monkeypatch):
    private = tmp_path / ".env.local"
    public = tmp_path / ".env.development"
    public.write_text("GOOGLE_CLIENT_ID=dev-client.apps.googleusercontent.com\n", encoding="utf-8")
    monkeypatch.setattr(dev, "PRIVATE_CONFIG", private)
    monkeypatch.setattr(dev, "PUBLIC_CONFIG", public)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    # Without the line, the launcher still starts and leaves the assistant switched off.
    private.write_text("JWT_SECRET=" + "s" * 48 + "\n", encoding="utf-8")
    dev.configure_environment()
    assert "GEMINI_API_KEY" not in dev.os.environ

    private.write_text("JWT_SECRET=" + "s" * 48 + "\nGEMINI_API_KEY=test-key\n", encoding="utf-8")
    dev.configure_environment()
    assert dev.os.environ["GEMINI_API_KEY"] == "test-key"

    # An exported key still wins over the file.
    monkeypatch.setenv("GEMINI_API_KEY", "exported-key")
    dev.configure_environment()
    assert dev.os.environ["GEMINI_API_KEY"] == "exported-key"


def test_dev_run_migrates_before_serving(monkeypatch):
    calls = []
    monkeypatch.setattr(dev, "configure_environment", lambda: calls.append("configure"))
    monkeypatch.setattr(migrate, "upgrade", lambda: calls.append("migrate"))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(("serve", args, kwargs)))

    dev.run()
    assert calls == ["configure", "migrate", ("serve", ("app.main:app",), {
        "host": "127.0.0.1", "port": 8000, "reload": True, "access_log": False,
    })]


def test_dev_run_does_not_serve_when_migration_is_refused(monkeypatch):
    def refuse():
        raise RuntimeError("Existing unversioned schema differs from the current models.")

    served = []
    monkeypatch.setattr(dev, "configure_environment", lambda: None)
    monkeypatch.setattr(migrate, "upgrade", refuse)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: served.append(args))
    with pytest.raises(SystemExit, match="differs"):
        dev.run()
    assert served == []


def test_dev_run_upgrades_a_sprint1_database(sprint1_database, monkeypatch):
    monkeypatch.setattr(dev, "configure_environment", lambda: None)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    dev.run()
    engine = build_engine(sprint1_database)
    try:
        current, head = schema_revision(engine)
        assert current == head
        assert "role" in {column["name"] for column in inspect(engine).get_columns("traveler")}
    finally:
        engine.dispose()
