import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import TypeAdapter, EmailStr


class ResetSender(Protocol):
    def send_reset(self, recipient: str, link: str) -> None: ...


@dataclass(frozen=True)
class MailSettings:
    frontend_url: str
    host: str
    from_email: str
    port: int = 587
    security: str = "starttls"
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    timeout: int = 10

    @classmethod
    def from_environment(cls):
        frontend = os.environ.get("RESET_FRONTEND_URL", "")
        host = os.environ.get("SMTP_HOST", "")
        if not frontend and not host:
            return None  # Existing auth remains usable without SMTP configuration.
        parsed = urlsplit(frontend)
        if (
            not host or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in frontend)
            or "\\" in frontend
            or (parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            ))
        ):
            raise RuntimeError("Set SMTP_HOST and a trusted RESET_FRONTEND_URL (HTTPS, or loopback HTTP; no query/fragment).")
        try:
            parsed.port  # Reject malformed ports at startup.
            sender = TypeAdapter(EmailStr).validate_python(os.environ.get("SMTP_FROM", ""))
            port = int(os.environ.get("SMTP_PORT", "587"))
            timeout = int(os.environ.get("SMTP_TIMEOUT_SECONDS", "10"))
            if not 1 <= port <= 65535 or not 1 <= timeout <= 60:
                raise ValueError
        except (ValueError, TypeError):
            raise RuntimeError("Set a valid SMTP_FROM, SMTP_PORT (1-65535), and SMTP_TIMEOUT_SECONDS (1-60).") from None
        security = os.environ.get("SMTP_SECURITY", "starttls").lower()
        username = os.environ.get("SMTP_USERNAME", "")
        password = os.environ.get("SMTP_PASSWORD", "")
        if security not in {"starttls", "ssl", "none"} or bool(username) != bool(password):
            raise RuntimeError("SMTP_SECURITY must be starttls, ssl, or none; supply both SMTP_USERNAME and SMTP_PASSWORD or neither.")
        if security == "none" and (host not in {"localhost", "127.0.0.1", "::1"} or username):
            raise RuntimeError("Unencrypted SMTP is restricted to a loopback mail catcher without credentials.")
        return cls(frontend, host, sender, port, security, username, password, timeout)


class SmtpResetSender:
    def __init__(self, settings: MailSettings):
        self.settings = settings

    def send_reset(self, recipient: str, link: str) -> None:
        settings = self.settings
        message = EmailMessage()
        message["From"] = settings.from_email
        message["To"] = recipient
        message["Subject"] = "Reset your Taasheera password"
        message.set_content(
            "Use this link to choose a new password for your traveler account:\n\n"
            f"{link}\n\nThis link expires in 30 minutes and can be used once.\n"
            "If you did not request this, ignore this email.\n"
        )
        context = ssl.create_default_context()
        if settings.security == "ssl":
            connection = smtplib.SMTP_SSL(settings.host, settings.port, timeout=settings.timeout, context=context)
        else:
            connection = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
        # Never enable SMTP debug output: it exposes message bodies and credentials.
        with connection as smtp:
            smtp.ehlo()
            if settings.security == "starttls":
                smtp.starttls(context=context)
                smtp.ehlo()
            if settings.username:
                smtp.login(settings.username, settings.password)
            if smtp.send_message(message):
                raise smtplib.SMTPException("Reset email was not accepted.")
