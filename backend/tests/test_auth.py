from concurrent.futures import ThreadPoolExecutor
import secrets
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import AUDIENCE, COOKIE_NAME, ISSUER, token_hash
from app.main import create_app
from app.models import AuthSession, RefreshToken


PASSWORD = "Traveler-password-123"


@pytest.fixture
def api(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    with TestClient(app) as client:
        response = client.post("/auth/register", json={
            "name": "Maya", "email": "maya@example.com", "password": PASSWORD,
        })
        assert response.status_code == 201
        yield client, app


def login(client, **changes):
    return client.post("/auth/login", json={
        "email": "MAYA@example.com", "password": PASSWORD, **changes,
    })


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def set_cookie(client, raw):
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, raw, domain="testserver.local", path="/auth")


def test_login_me_cookie_and_hashed_refresh_storage(api):
    client, app = api
    response = login(client)
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.json()["token_type"] == "bearer"
    assert 0 < response.json()["expires_in"] <= 900
    assert response.headers["cache-control"] == "no-store"
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert "Path=/auth" in cookie_header
    assert "Domain=" not in cookie_header
    assert "Secure" not in cookie_header  # Local HTTP configuration.
    raw = client.cookies.get(COOKIE_NAME)
    assert raw not in response.text
    assert PASSWORD not in response.text
    with Session(app.state.engine) as session:
        stored = session.exec(select(RefreshToken)).one()
        assert stored.token_hash == token_hash(raw)
        assert stored.token_hash != raw
        auth_session = session.exec(select(AuthSession)).one()
        assert auth_session.refresh_hash == stored.token_hash
    profile = client.get("/auth/me", headers=bearer(response))
    assert profile.status_code == 200
    assert profile.json() == {"id": 1, "name": "Maya", "email": "maya@example.com"}
    assert profile.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("payload", [
    {"email": "invalid", "password": PASSWORD},
    {"email": "maya@example.com"},
    {"password": PASSWORD},
    {"email": "maya@example.com", "password": PASSWORD, "role": "admin"},
])
def test_login_validation_does_not_echo_password_or_create_session(api, payload):
    client, app = api
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert "set-cookie" not in response.headers
    assert all(set(error) == {"loc", "msg", "type"} for error in response.json()["detail"])
    with Session(app.state.engine) as session:
        assert session.exec(select(AuthSession)).all() == []


@pytest.mark.parametrize("wrong", ["incorrect-password", "", "a" * 73, "é" * 37])
def test_unknown_email_and_incorrect_password_have_identical_errors(api, wrong):
    client, app = api
    unknown = login(client, email="missing@example.com", password=wrong)
    incorrect = login(client, password=wrong)
    assert unknown.status_code == incorrect.status_code == 401
    assert unknown.json() == incorrect.json() == {"detail": "Invalid email or password."}
    assert "set-cookie" not in unknown.headers
    assert "set-cookie" not in incorrect.headers
    with Session(app.state.engine) as session:
        assert session.exec(select(AuthSession)).all() == []


@pytest.mark.parametrize("authorization", [None, "Bearer nonsense", "Basic abc"])
def test_me_requires_valid_bearer_token(api, authorization):
    client, _ = api
    login(client)  # A refresh cookie alone must not authorize /me.
    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("case", [
    "expired", "signature", "algorithm", "audience", "issuer", "type",
    "missing_exp", "future_iat", "subject", "session", "malformed_session", "malformed_exp",
])
def test_invalid_jwt_claims_and_signatures_are_rejected(api, case):
    client, app = api
    response = login(client)
    secret = app.state.auth_settings.jwt_secret
    claims = jwt.decode(response.json()["access_token"], secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER)
    algorithm = "HS256"
    if case == "expired":
        claims["exp"] = int(time.time()) - 1
    elif case == "signature":
        secret = secrets.token_urlsafe(48)
    elif case == "algorithm":
        algorithm = "HS384"
    elif case == "audience":
        claims["aud"] = "other-app"
    elif case == "issuer":
        claims["iss"] = "other-issuer"
    elif case == "type":
        claims["type"] = "refresh"
    elif case == "missing_exp":
        del claims["exp"]
    elif case == "future_iat":
        claims["iat"] = int(time.time()) + 3600
    elif case == "subject":
        claims["sub"] = "999"
    elif case == "session":
        claims["sid"] = "missing-session"
    elif case == "malformed_exp":
        claims["exp"] = []
    else:
        claims["sid"] = ["invalid"]
    token = jwt.encode(claims, secret, algorithm=algorithm)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_refresh_rotates_and_replay_revokes_the_entire_session(api):
    client, app = api
    original = login(client)
    old_cookie = client.cookies.get(COOKIE_NAME)
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    new_cookie = client.cookies.get(COOKIE_NAME)
    assert new_cookie != old_cookie
    assert refreshed.json()["access_token"] != original.json()["access_token"]
    assert client.get("/auth/me", headers=bearer(refreshed)).status_code == 200
    with Session(app.state.engine) as session:
        assert len(session.exec(select(RefreshToken)).all()) == 2
        assert session.exec(select(AuthSession)).one().refresh_hash == token_hash(new_cookie)
    set_cookie(client, old_cookie)
    assert client.post("/auth/refresh").status_code == 401
    assert client.cookies.get(COOKIE_NAME) is None
    set_cookie(client, new_cookie)
    assert client.post("/auth/refresh").status_code == 401
    assert client.get("/auth/me", headers=bearer(original)).status_code == 401
    assert client.get("/auth/me", headers=bearer(refreshed)).status_code == 401


@pytest.mark.parametrize("raw", [None, "unknown-refresh-token"])
def test_refresh_requires_a_known_cookie(api, raw):
    client, _ = api
    if raw:
        set_cookie(client, raw)
    response = client.post("/auth/refresh")
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_expired_session_cannot_refresh_or_access_profile(api):
    client, app = api
    logged_in = login(client)
    with Session(app.state.engine) as session:
        auth_session = session.exec(select(AuthSession)).one()
        auth_session.expires_at = int(time.time()) - 1
        session.add(auth_session)
        session.commit()
    assert client.get("/auth/me", headers=bearer(logged_in)).status_code == 401
    assert client.post("/auth/refresh").status_code == 401


def test_expired_access_token_can_be_refreshed(api):
    client, app = api
    logged_in = login(client)
    secret = app.state.auth_settings.jwt_secret
    claims = jwt.decode(logged_in.json()["access_token"], secret, algorithms=["HS256"], audience=AUDIENCE)
    claims["exp"] = int(time.time()) - 1
    expired = jwt.encode(claims, secret, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert client.get("/auth/me", headers=bearer(refreshed)).status_code == 200


def test_logout_revokes_access_and_refresh_and_is_idempotent(api):
    client, _ = api
    logged_in = login(client)
    raw = client.cookies.get(COOKIE_NAME)
    response = client.post("/auth/logout")
    assert response.status_code == 204
    assert response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.cookies.get(COOKIE_NAME) is None
    assert client.get("/auth/me", headers=bearer(logged_in)).status_code == 401
    set_cookie(client, raw)
    assert client.post("/auth/refresh").status_code == 401
    assert client.post("/auth/logout").status_code == 204


def test_second_login_revokes_replaced_browser_session(api):
    client, _ = api
    first = login(client)
    second = login(client)
    assert client.get("/auth/me", headers=bearer(first)).status_code == 401
    assert client.get("/auth/me", headers=bearer(second)).status_code == 200


@pytest.mark.parametrize("path", ["/auth/login", "/auth/refresh", "/auth/logout"])
def test_untrusted_origin_is_rejected_without_revoking_session(api, path):
    client, _ = api
    logged_in = login(client)
    response = client.post(path, headers={"Origin": "https://untrusted.example"}, json={})
    assert response.status_code == 403
    assert client.get("/auth/me", headers=bearer(logged_in)).status_code == 200
    assert client.post("/auth/refresh", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


def test_concurrent_refresh_has_only_one_winner_and_revokes_on_reuse(api):
    client, app = api
    login(client)
    raw = client.cookies.get(COOKIE_NAME)

    def refresh_once():
        # Separate clients prevent shared cookie-jar updates between threads.
        other = TestClient(app)
        try:
            set_cookie(other, raw)
            return other.post("/auth/refresh")
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: refresh_once(), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 401]
    winner = next(response for response in responses if response.status_code == 200)
    assert client.get("/auth/me", headers=bearer(winner)).status_code == 401


@pytest.mark.parametrize("secret", [None, "too-short"])
def test_missing_or_weak_signing_secret_prevents_startup(tmp_path, monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("JWT_SECRET")
    else:
        monkeypatch.setenv("JWT_SECRET", secret)
    app = create_app(f"sqlite:///{(tmp_path / 'config.db').as_posix()}")
    with pytest.raises(RuntimeError, match="Set JWT_SECRET"):
        with TestClient(app):
            pass


def test_secure_cookie_is_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTH_COOKIE_SECURE")
    app = create_app(f"sqlite:///{(tmp_path / 'secure.db').as_posix()}")
    with TestClient(app, base_url="https://testserver") as client:
        client.post("/auth/register", json={"name": "Maya", "email": "maya@example.com", "password": PASSWORD})
        response = login(client)
        assert "Secure" in response.headers["set-cookie"]
        assert client.post("/auth/refresh").status_code == 200
        assert "Secure" in client.post("/auth/logout").headers["set-cookie"]


def test_logout_does_not_revoke_another_device(api):
    client, app = api
    first = login(client)
    other = TestClient(app)
    try:
        second = login(other)
        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/me", headers=bearer(first)).status_code == 401
        assert other.get("/auth/me", headers=bearer(second)).status_code == 200
        assert other.post("/auth/refresh").status_code == 200
    finally:
        other.close()


def test_cross_site_fetch_without_origin_is_rejected(api):
    client, _ = api
    login(client)
    assert client.post("/auth/refresh", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_refresh_does_not_extend_session_lifetime(api):
    client, app = api
    login(client)
    with Session(app.state.engine) as session:
        auth_session = session.exec(select(AuthSession)).one()
        auth_session.expires_at = int(time.time()) + 60
        deadline = auth_session.expires_at
        session.add(auth_session)
        session.commit()
    response = client.post("/auth/refresh")
    assert response.status_code == 200
    assert 0 < response.json()["expires_in"] <= 60
    with Session(app.state.engine) as session:
        assert session.exec(select(AuthSession)).one().expires_at == deadline
