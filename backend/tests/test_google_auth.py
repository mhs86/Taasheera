import sqlite3
import time
from unittest.mock import Mock

import bcrypt
import pytest
from fastapi.testclient import TestClient
from google.auth import exceptions
from sqlmodel import Session, select

from app.auth import COOKIE_NAME, token_hash
from app.config import AuthSettings
from app.main import create_app
from app.models import AuthSession, GoogleIdentity, PasswordResetToken, RefreshToken, Traveler


CLIENT_ID = "test-web-client.apps.googleusercontent.com"
TOKEN = "test-google-id-token-not-a-real-credential"
EMAIL = "maya@example.com"
PASSWORD = "Traveler-password-123"


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    verifier = Mock(return_value={
        "iss": "https://accounts.google.com", "aud": CLIENT_ID,
        "exp": int(time.time()) + 3600, "sub": "google-subject-123",
        "email": "MAYA@example.com", "email_verified": True, "name": " Maya Haddad ",
    })
    monkeypatch.setattr("app.google_auth.id_token.verify_oauth2_token", verifier)
    # A missed mock must fail instead of contacting Google or another service.
    def forbid_network(*args, **kwargs):
        raise AssertionError("Tests must not make network requests")
    monkeypatch.setattr("requests.Session.request", forbid_network)
    return verifier


@pytest.fixture
def api(tmp_path, monkeypatch, google):
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("RESET_FRONTEND_URL", "http://127.0.0.1:5173/reset-password")
    sender = Mock()
    app = create_app(f"sqlite:///{(tmp_path / 'google.db').as_posix()}", reset_sender=sender)
    with TestClient(app) as client:
        yield client, app, sender


def sign_in(client):
    return client.post("/auth/google", json={"id_token": TOKEN})


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_first_sign_in_creates_identity_and_uses_existing_session_contract(api, google, caplog):
    client, app, _ = api
    response = sign_in(client)
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.json()["token_type"] == "bearer"
    assert 0 < response.json()["expires_in"] <= 900
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/auth" in cookie
    assert "Secure" not in cookie
    assert TOKEN not in response.text and TOKEN not in caplog.text
    args, kwargs = google.call_args
    assert args[0] == TOKEN and callable(args[1])
    assert kwargs["audience"] == CLIENT_ID
    profile = client.get("/auth/me", headers=bearer(response))
    assert profile.json() == {"id": 1, "name": "Maya Haddad", "email": EMAIL}
    assert client.get("/auth/me").status_code == 401  # Cookie alone is insufficient.
    with Session(app.state.engine) as session:
        traveler = session.exec(select(Traveler)).one()
        identity = session.exec(select(GoogleIdentity)).one()
        assert traveler.password_hash == ""
        assert identity.subject == "google-subject-123" and identity.traveler_id == traveler.id
        stored = session.exec(select(RefreshToken)).one()
        assert stored.token_hash == token_hash(client.cookies.get(COOKIE_NAME))
        assert session.exec(select(AuthSession)).one().traveler_id == traveler.id


def test_returning_identity_uses_sub_even_when_email_changes(api, google):
    client, app, _ = api
    first = sign_in(client)
    google.return_value = {**google.return_value, "email": "changed@example.com", "name": "Changed Name"}
    second = sign_in(client)
    assert second.status_code == 200
    assert client.get("/auth/me", headers=bearer(second)).json() == {
        "id": 1, "name": "Maya Haddad", "email": EMAIL,
    }
    assert client.get("/auth/me", headers=bearer(first)).status_code == 401
    with Session(app.state.engine) as session:
        assert len(session.exec(select(Traveler)).all()) == 1
        assert len(session.exec(select(GoogleIdentity)).all()) == 1


@pytest.mark.parametrize("failure", [ValueError("Invalid signature"), ValueError("Token expired"), exceptions.GoogleAuthError("Invalid issuer")])
def test_verifier_rejection_creates_no_account_or_session(api, google, failure):
    client, app, _ = api
    google.side_effect = failure
    response = sign_in(client)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert TOKEN not in response.text
    with Session(app.state.engine) as session:
        assert session.exec(select(Traveler)).all() == []
        assert session.exec(select(GoogleIdentity)).all() == []
        assert session.exec(select(AuthSession)).all() == []


@pytest.mark.parametrize("field,value", [
    ("email_verified", False), ("email_verified", "true"), ("email_verified", None),
    ("sub", None), ("sub", ""), ("sub", "   "), ("sub", 123), ("sub", []), ("sub", "x" * 256),
    ("exp", 1), ("exp", None), ("exp", "9999999999"),
    ("aud", "another-client.apps.googleusercontent.com"), ("iss", "https://evil.example"),
    ("email", "not-an-email"), ("email", None),
])
def test_invalid_claims_are_rejected(api, google, field, value):
    client, app, _ = api
    google.return_value = {**google.return_value, field: value}
    assert sign_in(client).status_code == 401
    with Session(app.state.engine) as session:
        assert session.exec(select(Traveler)).all() == []
        assert session.exec(select(AuthSession)).all() == []


def test_missing_sub_is_rejected(api, google):
    client, _, _ = api
    del google.return_value["sub"]
    assert sign_in(client).status_code == 401


def test_email_collision_does_not_link_or_sign_in_and_password_still_works(api):
    client, app, _ = api
    registered = client.post("/auth/register", json={"name": "Original", "email": EMAIL, "password": PASSWORD})
    assert registered.status_code == 201
    with Session(app.state.engine) as session:
        original_hash = session.exec(select(Traveler)).one().password_hash
    response = sign_in(client)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "google_link_required"
    assert "set-cookie" not in response.headers
    with Session(app.state.engine) as session:
        assert session.exec(select(GoogleIdentity)).all() == []
        assert session.exec(select(AuthSession)).all() == []
        traveler = session.exec(select(Traveler)).one()
        assert traveler.name == "Original" and traveler.password_hash == original_hash
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200


def test_different_google_subject_with_same_email_is_not_linked(api, google):
    client, app, _ = api
    original = sign_in(client)
    google.return_value = {**google.return_value, "sub": "different-google-subject"}
    assert sign_in(client).status_code == 409
    assert client.get("/auth/me", headers=bearer(original)).status_code == 200
    with Session(app.state.engine) as session:
        assert len(session.exec(select(GoogleIdentity)).all()) == 1


def test_google_only_account_cannot_use_password_login_registration_or_reset(api):
    client, app, sender = api
    assert sign_in(client).status_code == 200
    for password in ("", PASSWORD):
        response = client.post("/auth/login", json={"email": EMAIL, "password": password})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password."}
    assert client.post("/auth/register", json={"name": "Other", "email": EMAIL, "password": PASSWORD}).status_code == 409
    requested = client.post("/auth/forgot-password", json={"email": EMAIL})
    unknown = client.post("/auth/forgot-password", json={"email": "missing@example.com"})
    assert requested.status_code == unknown.status_code == 202
    assert requested.json() == unknown.json()
    sender.send_reset.assert_not_called()
    with Session(app.state.engine) as session:
        assert session.exec(select(PasswordResetToken)).all() == []
        # Defense in depth: even a stray token cannot enable a password.
        session.add(PasswordResetToken(token_hash=token_hash("stray-token"), traveler_id=1, expires_at=int(time.time()) + 1800))
        session.commit()
    assert client.post("/auth/reset-password", json={"token": "stray-token", "password": PASSWORD}).status_code == 400
    with Session(app.state.engine) as session:
        assert session.get(Traveler, 1).password_hash == ""


def test_google_session_refresh_logout_and_other_device(api):
    client, app, _ = api
    first = sign_in(client)
    old_cookie = client.cookies.get(COOKIE_NAME)
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get(COOKIE_NAME) != old_cookie
    assert client.get("/auth/me", headers=bearer(refreshed)).status_code == 200
    other = TestClient(app)
    try:
        other_login = sign_in(other)
        assert client.post("/auth/logout").status_code == 204
        assert client.cookies.get(COOKIE_NAME) is None
        assert client.get("/auth/me", headers=bearer(first)).status_code == 401
        assert client.get("/auth/me", headers=bearer(refreshed)).status_code == 401
        assert client.post("/auth/refresh").status_code == 401
        assert client.post("/auth/logout").status_code == 204
        assert other.get("/auth/me", headers=bearer(other_login)).status_code == 200
    finally:
        other.close()


def test_untrusted_origin_is_rejected_before_verification(api, google):
    client, _, _ = api
    assert client.post("/auth/google", json={"id_token": TOKEN}, headers={"Origin": "https://evil.example"}).status_code == 403
    google.assert_not_called()


def test_verification_transport_failure_is_retryable(api, google, caplog):
    client, _, _ = api
    google.side_effect = exceptions.TransportError(TOKEN)
    response = sign_in(client)
    assert response.status_code == 503
    assert TOKEN not in response.text and TOKEN not in caplog.text


def test_unconfigured_google_sign_in_is_disabled(tmp_path, google, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'disabled.db').as_posix()}")) as client:
        assert sign_in(client).status_code == 503
    google.assert_not_called()


def test_invalid_client_configuration_fails_startup(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "not-a-web-client")
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        AuthSettings.from_environment()


def test_request_validation_omits_id_token(api, google):
    client, _, _ = api
    response = client.post("/auth/google", json={"id_token": TOKEN, "extra": True})
    assert response.status_code == 422 and TOKEN not in response.text
    google.assert_not_called()


def test_existing_local_traveler_table_and_accounts_survive_startup(tmp_path, google):
    path = tmp_path / "legacy.db"
    original_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE traveler (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, email VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(60) NOT NULL)")
        connection.execute("INSERT INTO traveler VALUES (?, ?, ?, ?)", (7, "Existing", "existing@example.com", original_hash))
    app = create_app(f"sqlite:///{path.as_posix()}")
    with TestClient(app) as client:
        assert sign_in(client).status_code == 200
        assert client.post("/auth/login", json={"email": "existing@example.com", "password": PASSWORD}).status_code == 200
        with Session(app.state.engine) as session:
            assert session.get(Traveler, 7).password_hash == original_hash
            assert len(session.exec(select(Traveler)).all()) == 2
