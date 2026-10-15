"""Database-backed admission limits and metadata-only authentication audit logs."""

import hashlib
import hmac
import ipaddress
import logging
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from .models import ResetRateLimit
from .observability import RequestJsonFormatter


security_log = logging.getLogger("taasheera.security")


def audit(request: Request, operation: str, outcome: str, traveler_id: int | None = None):
    # Never accept arbitrary text, email, IP, provider errors, passwords or tokens.
    if not security_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RequestJsonFormatter())
        security_log.addHandler(handler)
    security_log.setLevel(logging.INFO)
    security_log.propagate = False
    security_log.info("authentication", extra={"activity": {
        "request_id": getattr(request.state, "request_id", None),
        "operation": operation, "outcome": outcome, "traveler_id": traveler_id,
    }})


def client_address(request: Request) -> str:
    # The AWS nginx config overwrites this header with CloudFront's generated
    # viewer address. Enable only behind that private, origin-protected proxy.
    if request.app.state.auth_settings.trust_cloudfront_proxy:
        raw = request.headers.get("x-taasheera-client-ip", "")
        try:
            host = urlsplit("//" + raw).hostname
            return str(ipaddress.ip_address(host))
        except (ValueError, TypeError):
            pass
    return request.client.host if request.client else "unknown"


def consume_limit(session: Session, scope: str, value: str, limit: int, seconds: int,
                  now: int, *, secret: str = "") -> bool:
    digest = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    key = f"{scope}:{digest}"
    session.execute(delete(ResetRateLimit).where(ResetRateLimit.expires_at <= now))
    result = session.execute(update(ResetRateLimit).where(
        ResetRateLimit.key == key, ResetRateLimit.count < limit,
    ).values(count=ResetRateLimit.count + 1))
    if result.rowcount:
        return True
    try:
        with session.begin_nested():
            session.add(ResetRateLimit(key=key, expires_at=now + seconds))
            session.flush()
        return True
    except IntegrityError:
        result = session.execute(update(ResetRateLimit).where(
            ResetRateLimit.key == key, ResetRateLimit.count < limit,
        ).values(count=ResetRateLimit.count + 1))
        return result.rowcount == 1


def admitted(request: Request, session: Session, limits: list[tuple[str, str, int, int]]) -> bool:
    secret = request.app.state.auth_settings.jwt_secret
    now = int(time.time())
    allowed = True
    for scope, value, count, seconds in limits:
        if not consume_limit(session, scope, value, count, seconds, now, secret=secret):
            allowed = False
            break
    # Admission must survive rejected requests and process/container restarts.
    session.commit()
    return allowed


def throttle(request: Request, session: Session, operation: str,
             *, account: str | None = None, ip_limit: int = 30, account_limit: int = 10):
    limits = [(f"{operation}-ip", client_address(request), ip_limit, 900)]
    if account is not None:
        limits.append((f"{operation}-account", account, account_limit, 900))
    if not admitted(request, session, limits):
        audit(request, operation, "throttled")
        raise HTTPException(429, "Too many attempts. Please try again later.",
                            headers={"Cache-Control": "no-store", "Retry-After": "900"})
