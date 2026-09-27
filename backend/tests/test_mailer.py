import secrets

import pytest

from app.mailer import MailSettings, SmtpResetSender


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("RESET_FRONTEND_URL", "https://travel.example.com/reset-password")


@pytest.mark.parametrize("name,value", [
    ("RESET_FRONTEND_URL", "http://evil.example/reset"),
    ("RESET_FRONTEND_URL", "https://user:password@example.com/reset"),
    ("RESET_FRONTEND_URL", "https://example.com/reset?next=evil"),
    ("RESET_FRONTEND_URL", "https://example.com/reset#fragment"),
    ("RESET_FRONTEND_URL", "//example.com/reset"),
    ("RESET_FRONTEND_URL", "https://example.com:invalid/reset"),
    ("SMTP_FROM", "not-an-email"),
    ("SMTP_PORT", "0"),
    ("SMTP_TIMEOUT_SECONDS", "0"),
    ("SMTP_SECURITY", "invalid"),
    ("SMTP_SECURITY", "none"),
    ("SMTP_USERNAME", "unpaired-user"),
])
def test_invalid_mail_configuration_fails_early(configured, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        MailSettings.from_environment()


def test_local_mail_catcher_needs_no_credentials(configured, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_SECURITY", "none")
    monkeypatch.setenv("RESET_FRONTEND_URL", "http://127.0.0.1:5173/reset-password")
    settings = MailSettings.from_environment()
    assert settings.port == 1025 and settings.security == "none"
    assert not settings.username and not settings.password


@pytest.mark.parametrize("security", ["starttls", "ssl", "none"])
def test_smtp_sender_transport_message_and_credentials(monkeypatch, security, caplog):
    events = []

    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            events.append(("connect", host, port, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append(("close",))

        def ehlo(self):
            events.append(("ehlo",))

        def starttls(self, **kwargs):
            assert kwargs["context"].check_hostname
            events.append(("tls",))

        def login(self, username, password):
            events.append(("login", username, password))

        def send_message(self, message):
            events.append(("message", message))
            return {}

    def ssl_smtp(*args, **kwargs):
        assert kwargs["context"].check_hostname
        events.append(("ssl",))
        return FakeSMTP(*args, **kwargs)

    monkeypatch.setattr("app.mailer.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.mailer.smtplib.SMTP_SSL", ssl_smtp)
    password = secrets.token_urlsafe(32)
    settings = MailSettings("https://example.com/reset", "smtp.example.com", "no-reply@example.com",
                            security=security, username="test-user" if security != "none" else "",
                            password=password if security != "none" else "")
    link = "https://example.com/reset#token=" + secrets.token_urlsafe(32)
    SmtpResetSender(settings).send_reset("maya@example.com", link)
    names = [event[0] for event in events]
    assert ("ssl" in names) == (security == "ssl")
    assert ("tls" in names) == (security == "starttls")
    assert ("login" in names) == (security != "none")
    if security == "starttls":
        assert names.index("tls") < names.index("login") < names.index("message")
    message = next(event[1] for event in events if event[0] == "message")
    assert message["To"] == "maya@example.com"
    assert message["From"] == "no-reply@example.com"
    assert link in message.get_content()
    assert "30 minutes" in message.get_content()
    assert link not in caplog.text and password not in caplog.text and password not in repr(settings)
