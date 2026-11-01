"""Existing users explicitly prove both credentials at the Google sign-in screen."""
from unittest.mock import Mock
import time

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import create_app
from app.models import ActivityEvent, GoogleIdentity, Traveler

PASSWORD = "Synthetic-password-123"
TOKEN = "synthetic-google-token"
EMAIL = "existing@example.com"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
    verifier = Mock(return_value={"iss": "https://accounts.google.com", "aud": "test.apps.googleusercontent.com",
        "exp": int(time.time()) + 3600, "sub": "synthetic-subject", "email": EMAIL.upper(),
        "email_verified": True, "name": "Provider name"})
    monkeypatch.setattr("app.google_auth.id_token.verify_oauth2_token", verifier)
    monkeypatch.setattr("requests.Session.request", Mock(side_effect=AssertionError("No real Google calls")))
    app = create_app(f"sqlite:///{tmp_path / 'link-login.db'}")
    with TestClient(app) as client:
        with Session(app.state.engine) as session:
            session.add(Traveler(name="Existing owner", email=EMAIL, role="admin",
                password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()))
            session.commit()
        yield client, app, verifier


def complete(client, **changes):
    return client.post("/auth/google/link-login", json={"id_token": TOKEN, "password": PASSWORD, **changes})


def test_collision_requires_confirmation_then_preserves_owner_role_and_password(api, caplog):
    client, app, _ = api
    with Session(app.state.engine) as session:
        original = session.get(Traveler, 1).password_hash
    collision = client.post("/auth/google", json={"id_token": TOKEN})
    assert collision.status_code == 409
    assert collision.json()["detail"]["code"] == "google_link_required"
    result = complete(client)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert "HttpOnly" in result.headers["set-cookie"]
    headers = {"Authorization": "Bearer " + result.json()["access_token"]}
    assert client.get("/auth/me", headers=headers).json()["name"] == "Existing owner"
    assert client.get("/admin/me", headers=headers).status_code == 200
    with Session(app.state.engine) as session:
        owner = session.get(Traveler, 1)
        assert owner.password_hash == original and owner.email == EMAIL and owner.role == "admin"
        assert session.exec(select(GoogleIdentity)).one().traveler_id == 1
        assert len(session.exec(select(Traveler)).all()) == 1
        assert len(session.exec(select(ActivityEvent).where(ActivityEvent.event_type == "account_link")).all()) == 1
    assert complete(client).status_code == 200  # Safe retry after a lost response.
    assert client.post("/auth/google", json={"id_token": TOKEN}).status_code == 200
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert TOKEN not in caplog.text and PASSWORD not in caplog.text


@pytest.mark.parametrize("case,status", [("password", 401), ("unverified", 401), ("expired", 401),
    ("audience", 401), ("unknown", 401), ("google_only", 401), ("suspended", 403),
    ("subject_owned", 409), ("different_link", 409)])
def test_link_login_refuses_invalid_credentials_and_conflicts_without_mutating_identity(api, case, status):
    client, app, verifier = api
    changes = {}
    with Session(app.state.engine) as session:
        owner = session.get(Traveler, 1)
        if case == "password": changes["password"] = "Wrong-password-123"
        if case == "unverified": verifier.return_value["email_verified"] = False
        if case == "expired": verifier.return_value["exp"] = int(time.time()) - 1
        if case == "audience": verifier.return_value["aud"] = "other.apps.googleusercontent.com"
        if case == "unknown": verifier.return_value["email"] = "unknown@example.com"
        if case == "google_only": owner.password_hash = ""; owner.auth_type = "google"
        if case == "suspended": owner.status = "suspended"
        if case == "subject_owned":
            other = Traveler(name="Other", email="other@example.com", password_hash="", auth_type="google")
            session.add(other); session.flush()
            session.add(GoogleIdentity(subject="synthetic-subject", traveler_id=other.id))
        if case == "different_link": session.add(GoogleIdentity(subject="other-subject", traveler_id=1))
        session.add(owner); session.commit()
        before = [(x.subject, x.traveler_id) for x in session.exec(select(GoogleIdentity))]
    response = complete(client, **changes)
    assert response.status_code == status
    assert "set-cookie" not in response.headers
    with Session(app.state.engine) as session:
        assert [(x.subject, x.traveler_id) for x in session.exec(select(GoogleIdentity))] == before
        assert session.get(Traveler, 1).sso_email is None


def test_link_login_origin_input_validation_and_shared_password_rate_limit(api):
    client, app, verifier = api
    assert client.post("/auth/google/link-login", headers={"Origin": "https://evil.example"},
                       json={"id_token": TOKEN, "password": PASSWORD}).status_code == 403
    assert complete(client, role="admin").status_code == 422
    verifier.assert_not_called()
    for _ in range(10):
        assert client.post("/auth/login", json={"email": EMAIL, "password": "wrong-password"}).status_code == 401
    assert complete(client).status_code == 429
    with Session(app.state.engine) as session:
        assert session.exec(select(GoogleIdentity)).all() == []
