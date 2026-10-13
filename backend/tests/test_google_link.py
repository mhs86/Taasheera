import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import create_app
from app.models import GoogleIdentity, Traveler

EMAIL = "mhs86@mail.aub.edu"
PASSWORD = "test-password-for-link-123"
CLIENT = "runtime-client.apps.googleusercontent.com"
TOKEN = "synthetic-google-credential"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT)
    verifier = Mock(return_value={"iss": "https://accounts.google.com", "aud": CLIENT,
                                 "exp": int(time.time()) + 3600, "sub": "subject-owner",
                                 "email": EMAIL.upper(), "email_verified": True, "name": "Google owner"})
    monkeypatch.setattr("app.google_auth.id_token.verify_oauth2_token", verifier)
    monkeypatch.setattr("requests.Session.request", Mock(side_effect=AssertionError("No real Google calls")))
    app = create_app(f"sqlite:///{tmp_path / 'link.db'}")
    with TestClient(app) as client:
        assert client.post("/auth/register", json={"name": "Owner", "email": EMAIL, "password": PASSWORD}).status_code == 201
        login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        yield client, app, headers, verifier


def link(client, headers, **changes):
    return client.post("/auth/google/link", headers=headers,
                       json={"id_token": TOKEN, "password": PASSWORD, "expected_traveler_id": 1, **changes})


def test_public_runtime_config_exposes_only_client_id(api, monkeypatch):
    client, app, _, verifier = api
    response = client.get("/auth/config")
    assert response.json() == {"google_client_id": CLIENT}
    assert response.headers["cache-control"] == "no-store"
    assert app.state.auth_settings.jwt_secret not in response.text
    verifier.assert_not_called()


def test_runtime_config_can_disable_google(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'disabled.db'}")) as client:
        assert client.get("/auth/config").json() == {"google_client_id": None}


def test_owner_explicitly_links_then_uses_google_and_password(api, caplog):
    client, app, headers, verifier = api
    with Session(app.state.engine) as session:
        original = session.get(Traveler, 1).password_hash
    response = link(client, headers)
    assert response.status_code == 200
    assert response.json() == {"id": 1, "name": "Owner", "email": EMAIL, "sso_email": EMAIL}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert TOKEN not in response.text and PASSWORD not in caplog.text and TOKEN not in caplog.text
    assert client.get("/auth/me", headers=headers).json()["sso_email"] == EMAIL
    with Session(app.state.engine) as session:
        assert session.get(Traveler, 1).password_hash == original
        assert session.exec(select(GoogleIdentity)).one().traveler_id == 1
    assert client.post("/auth/logout").status_code == 204
    signed_in = client.post("/auth/google", json={"id_token": TOKEN})
    assert signed_in.status_code == 200
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + signed_in.json()["access_token"]}).json()["id"] == 1
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200


def test_link_requires_authenticated_owner_and_password(api):
    client, app, headers, verifier = api
    assert link(client, {}).status_code == 401
    assert link(client, headers, password="wrong-password-123").status_code == 403
    verifier.assert_not_called()
    with Session(app.state.engine) as session:
        assert session.exec(select(GoogleIdentity)).all() == []
        assert session.get(Traveler, 1).sso_email is None


def test_cross_origin_link_and_client_supplied_email_are_rejected(api):
    client, app, headers, verifier = api
    assert link(client, {**headers, "Origin": "https://untrusted.invalid"}).status_code == 403
    response = link(client, headers, sso_email=EMAIL)
    assert response.status_code == 422 and TOKEN not in response.text and PASSWORD not in response.text
    verifier.assert_not_called()


def test_changed_browser_account_cannot_link_a_different_owner(api):
    client, app, headers, verifier = api
    response = link(client, headers, expected_traveler_id=2)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "account_changed"
    verifier.assert_not_called()
    with Session(app.state.engine) as session:
        assert session.exec(select(GoogleIdentity)).all() == []


def test_unverified_google_email_cannot_link(api):
    client, app, headers, verifier = api
    verifier.return_value["email_verified"] = False
    assert link(client, headers).status_code == 401
    with Session(app.state.engine) as session:
        assert session.exec(select(GoogleIdentity)).all() == []


def test_link_is_idempotent_and_cannot_replace_google_subject(api):
    client, app, headers, verifier = api
    assert link(client, headers).status_code == 200
    assert link(client, headers).status_code == 200
    verifier.return_value["sub"] = "different-google-account"
    assert link(client, headers).status_code == 409
    with Session(app.state.engine) as session:
        assert session.exec(select(GoogleIdentity)).one().subject == "subject-owner"


def test_google_link_stores_a_different_verified_email_without_changing_contact_email(api):
    client, app, headers, verifier = api
    verifier.return_value["email"] = "different-google@example.com"
    response = link(client, headers)
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    assert response.json()["sso_email"] == "different-google@example.com"
    with Session(app.state.engine) as session:
        assert session.get(Traveler, 1).name == "Owner"


def test_google_subject_already_owned_by_another_traveler_is_not_moved(api):
    client, app, headers, verifier = api
    with Session(app.state.engine) as session:
        other = Traveler(name="Existing specimen", email="specimen@example.com", password_hash="")
        session.add(other); session.flush()
        session.add(GoogleIdentity(subject="subject-owner", traveler_id=other.id))
        session.commit()
    assert link(client, headers).status_code == 409
    with Session(app.state.engine) as session:
        assert session.get(GoogleIdentity, "subject-owner").traveler_id == 2
        assert session.get(Traveler, 1).sso_email is None
