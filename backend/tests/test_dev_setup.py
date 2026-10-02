import dev
from app.config import AuthSettings


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

    dev.configure_environment()
    settings = AuthSettings.from_environment()
    assert settings.jwt_secret == "s" * 48
    assert settings.google_client_id == "dev-client.apps.googleusercontent.com"
    assert settings.cookie_secure is False

    monkeypatch.setenv("JWT_SECRET", "p" * 48)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "override.apps.googleusercontent.com")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    dev.configure_environment()
    settings = AuthSettings.from_environment()
    assert settings.jwt_secret == "p" * 48
    assert settings.google_client_id == "override.apps.googleusercontent.com"
    assert settings.cookie_secure is True
