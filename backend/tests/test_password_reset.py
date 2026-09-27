from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import time
from urllib.parse import parse_qs, urlsplit

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import Session, select

from app.auth import COOKIE_NAME, token_hash
from app.main import create_app
from app.models import AuthSession, PasswordResetToken, ResetRateLimit, Traveler


OLD = "Original-password-123"
NEW = "Replacement-password-456"
EMAIL = "maya@example.com"


class FakeSender:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_reset(self, recipient, link):
        self.messages.append((recipient, link))
        if self.fail:
            raise RuntimeError(f"Simulated provider failure containing sensitive message {link}")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("RESET_FRONTEND_URL", "http://127.0.0.1:5173/reset-password")
    sender = FakeSender()
    app = create_app(f"sqlite:///{(tmp_path / 'reset.db').as_posix()}", reset_sender=sender)
    with TestClient(app) as client:
        assert client.post("/auth/register", json={"name": "Maya", "email": EMAIL, "password": OLD}).status_code == 201
        yield client, app, sender


def issue(api):
    client, _, sender = api
    assert client.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 202
    return parse_qs(urlsplit(sender.messages[-1][1]).fragment)["token"][0]


def reset(client, raw, password=NEW):
    return client.post("/auth/reset-password", content=json.dumps({"token": raw, "password": password}),
                       headers={"Content-Type": "application/json"})


def login(client, password=OLD):
    return client.post("/auth/login", json={"email": EMAIL, "password": password})


def clear_limits(app):
    with Session(app.state.engine) as session:
        session.execute(delete(ResetRateLimit))
        session.commit()


def test_known_unknown_and_limited_email_responses_match_and_only_hash_is_stored(api, caplog):
    client, app, sender = api
    known = client.post("/auth/forgot-password", json={"email": " MAYA@EXAMPLE.COM "},
                        headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"})
    unknown = client.post("/auth/forgot-password", json={"email": "missing@example.com"})
    limited = client.post("/auth/forgot-password", json={"email": EMAIL})
    assert known.status_code == unknown.status_code == limited.status_code == 202
    assert known.json() == unknown.json() == limited.json()
    assert known.headers["cache-control"] == "no-store"
    assert len(sender.messages) == 1
    recipient, link = sender.messages[0]
    assert recipient == EMAIL
    assert link.startswith("http://127.0.0.1:5173/reset-password#token=")
    raw = parse_qs(urlsplit(link).fragment)["token"][0]
    assert len(raw) == 43
    assert raw not in known.text and raw not in caplog.text and link not in caplog.text
    with Session(app.state.engine) as session:
        stored = session.exec(select(PasswordResetToken)).one()
        assert stored.token_hash == token_hash(raw) and stored.token_hash != raw
        assert 1795 <= stored.expires_at - int(time.time()) <= 1800
        assert not stored.used


def test_delivery_failure_is_generic_and_invalidates_link_without_logging(api, caplog):
    client, app, sender = api
    sender.fail = True
    failed = client.post("/auth/forgot-password", json={"email": EMAIL})
    unknown = client.post("/auth/forgot-password", json={"email": "missing@example.com"})
    assert failed.status_code == unknown.status_code == 202
    assert failed.json() == unknown.json()
    link = sender.messages[0][1]
    raw = parse_qs(urlsplit(link).fragment)["token"][0]
    assert link not in caplog.text and raw not in caplog.text
    with Session(app.state.engine) as session:
        assert session.exec(select(PasswordResetToken)).all() == []
    assert reset(client, raw).status_code == 400
    assert login(client).status_code == 200
    sender.fail = False
    clear_limits(app)
    assert reset(client, issue(api)).status_code == 204


@pytest.mark.parametrize("case", ["invalid", "expired", "reused"])
def test_invalid_expired_reused_tokens_have_same_error(api, case):
    client, app, _ = api
    raw = issue(api)
    if case == "invalid":
        raw = "unknown-reset-token"
    elif case == "expired":
        with Session(app.state.engine) as session:
            stored = session.get(PasswordResetToken, token_hash(raw))
            stored.expires_at = int(time.time())
            session.add(stored)
            session.commit()
    else:
        assert reset(client, raw).status_code == 204
    response = reset(client, raw)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired password reset token."}
    assert raw not in response.text and NEW not in response.text
    assert login(client, NEW if case == "reused" else OLD).status_code == 200


@pytest.mark.parametrize("password", ["x9!z", "a" * 73, "é" * 37, "password\ud800", None])
def test_password_rules_reject_without_consuming_link_or_echoing_values(api, password):
    client, _, _ = api
    raw = issue(api)
    response = reset(client, raw, password)
    assert response.status_code == 422
    assert raw not in response.text
    if password:
        assert password not in response.text
    assert all(set(error) == {"loc", "msg", "type"} for error in response.json()["detail"])
    assert reset(client, raw).status_code == 204


@pytest.mark.parametrize("password", ["é" * 36, "a" * 8, "  spaced password  "])
def test_password_boundaries_and_whitespace_are_preserved(api, password):
    client, app, _ = api
    assert reset(client, issue(api), password).status_code == 204
    assert login(client, password).status_code == 200
    with Session(app.state.engine) as session:
        stored = session.exec(select(Traveler)).one().password_hash
        assert stored.startswith("$2b$12$")
        assert bcrypt.checkpw(password.encode(), stored.encode())


def test_reset_revokes_all_links_and_all_device_sessions_requires_fresh_login(api, caplog):
    client, app, _ = api
    first = login(client)
    cookie = client.cookies.get(COOKIE_NAME)
    with TestClient(app) as other:
        second = login(other)
        raw1 = issue(api)
        clear_limits(app)
        raw2 = issue(api)
        response = reset(client, raw1)
        assert response.status_code == 204 and response.content == b""
        assert client.cookies.get(COOKIE_NAME) is None
        assert reset(client, raw2).status_code == 400
        for token in (first, second):
            assert client.get("/auth/me", headers={"Authorization": f"Bearer {token.json()['access_token']}"}).status_code == 401
        assert other.post("/auth/refresh").status_code == 401
        client.cookies.set(COOKIE_NAME, cookie, domain="testserver.local", path="/auth")
        assert client.post("/auth/refresh").status_code == 401
        assert login(client).status_code == 401
        fresh = login(client, NEW)
        assert fresh.status_code == 200
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}).status_code == 200
    assert OLD not in caplog.text and NEW not in caplog.text and raw1 not in caplog.text


@pytest.mark.parametrize("different_links", [False, True])
def test_simultaneous_resets_have_exactly_one_winner(api, different_links):
    client, app, _ = api
    raw = issue(api)
    clear_limits(app)
    second = issue(api) if different_links else raw
    gate = Barrier(2)

    def attempt(pair):
        with TestClient(app) as other:
            gate.wait(timeout=5)
            return pair[1], reset(other, *pair).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [(raw, NEW), (second, "Other-password-789")]))
    assert sorted(status for _, status in results) == [204, 400]
    for password, status in results:
        assert login(client, password).status_code == (200 if status == 204 else 401)
    assert login(client).status_code == 401


def test_rate_limits_apply_to_known_unknown_emails_and_client_ip(api):
    client, app, sender = api
    issue(api)
    for _ in range(7):
        assert client.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 202
    assert len(sender.messages) == 1
    clear_limits(app)
    for index in range(20):
        assert client.post("/auth/forgot-password", json={"email": f"missing{index}@example.com"}).status_code == 202
    assert client.post("/auth/forgot-password", json={"email": EMAIL}, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 202
    assert len(sender.messages) == 1
    with Session(app.state.engine) as session:
        buckets = session.exec(select(ResetRateLimit)).all()
        assert all(EMAIL not in bucket.key and "testclient" not in bucket.key for bucket in buckets)
        for bucket in buckets:
            bucket.expires_at = int(time.time()) - 1
            session.add(bucket)
        session.commit()
    issue(api)
    assert len(sender.messages) == 2


def test_confirmation_attempts_are_limited(api):
    client, _, _ = api
    for _ in range(60):
        assert reset(client, "not-a-token").status_code == 400
    response = reset(client, "not-a-token")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"


def test_hourly_email_limit_survives_minute_cooldown_and_new_app(api):
    client, app, sender = api
    for _ in range(5):
        issue(api)
        with Session(app.state.engine) as session:
            bucket = session.get(ResetRateLimit, f"email-minute:{token_hash(EMAIL)}")
            bucket.expires_at = int(time.time()) - 1
            session.add(bucket)
            session.commit()
    # A second app/process using the database cannot reset the allowance.
    replacement = create_app(str(app.state.engine.url), reset_sender=sender)
    with TestClient(replacement) as other:
        assert other.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 202
    assert len(sender.messages) == 5


def test_simultaneous_email_requests_send_at_most_one_message(api):
    _, app, sender = api
    gate = Barrier(2)

    def attempt(_):
        with TestClient(app) as other:
            gate.wait(timeout=5)
            return other.post("/auth/forgot-password", json={"email": EMAIL}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(attempt, range(2))) == [202, 202]
    assert len(sender.messages) == 1


def test_request_does_not_revoke_current_login_or_change_password(api):
    client, app, _ = api
    logged_in = login(client)
    issue(api)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"}).status_code == 200
    with Session(app.state.engine) as session:
        assert not session.exec(select(AuthSession)).one().revoked


def test_failed_transaction_preserves_password_token_and_sessions(api, monkeypatch):
    client, app, _ = api
    logged_in = login(client)
    raw = issue(api)

    def fail_hash(*args, **kwargs):
        raise RuntimeError("Simulated hashing failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.password_reset.bcrypt.hashpw", fail_hash)
        with pytest.raises(RuntimeError, match="Simulated hashing failure"):
            reset(client, raw)
    with Session(app.state.engine) as session:
        assert not session.get(PasswordResetToken, token_hash(raw)).used
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"}).status_code == 200
    assert login(client).status_code == 200
    assert reset(client, raw).status_code == 204


def test_reset_does_not_affect_another_traveler(api):
    client, app, _ = api
    with TestClient(app) as other:
        other.post("/auth/register", json={"name": "Other", "email": "other@example.com", "password": OLD})
        logged_in = other.post("/auth/login", json={"email": "other@example.com", "password": OLD})
        assert reset(client, issue(api)).status_code == 204
        assert other.get("/auth/me", headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"}).status_code == 200
        assert other.post("/auth/refresh").status_code == 200


@pytest.mark.parametrize("path,payload", [
    ("/auth/forgot-password", {"email": EMAIL}),
    ("/auth/reset-password", {"token": "test", "password": NEW}),
])
def test_untrusted_origin_is_rejected(api, path, payload):
    client, _, sender = api
    assert client.post(path, json=payload, headers={"Origin": "https://evil.example"}).status_code == 403
    assert sender.messages == []


def test_unconfigured_reset_is_unavailable_equally_for_every_email(tmp_path):
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'disabled.db').as_posix()}")) as client:
        for email in (EMAIL, "missing@example.com"):
            response = client.post("/auth/forgot-password", json={"email": email})
            assert response.status_code == 503
