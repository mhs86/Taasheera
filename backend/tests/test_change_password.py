import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import COOKIE_NAME, access_token
from app.main import create_app
from app.models import AuthSession, Traveler


OLD = "Current-password-123"
NEW = "Different-password-456"
EMAIL = "traveler@example.com"


@pytest.fixture
def api(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'change-password.db').as_posix()}")
    with TestClient(app) as client:
        assert client.post("/auth/register", json={
            "name": "Traveler", "email": EMAIL, "password": OLD,
        }).status_code == 201
        login = client.post("/auth/login", json={"email": EMAIL, "password": OLD})
        assert login.status_code == 200
        yield client, app, {"Authorization": f"Bearer {login.json()['access_token']}"}


def change(client, headers, **changes):
    return client.post("/auth/change-password", headers=headers, json={
        "current_password": OLD, "new_password": NEW, **changes,
    })


def test_change_password_success_keeps_current_session(api):
    client, app, headers = api
    response = change(client, headers)
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.post("/auth/refresh").status_code == 200
    with Session(app.state.engine) as session:
        traveler = session.get(Traveler, 1)
        assert bcrypt.checkpw(NEW.encode(), traveler.password_hash.encode())
        assert not bcrypt.checkpw(OLD.encode(), traveler.password_hash.encode())
    assert client.post("/auth/login", json={"email": EMAIL, "password": OLD}).status_code == 401
    assert client.post("/auth/login", json={"email": EMAIL, "password": NEW}).status_code == 200


def test_wrong_current_password_is_rejected_without_changing_hash(api):
    client, app, headers = api
    with Session(app.state.engine) as session:
        original = session.get(Traveler, 1).password_hash
    response = change(client, headers, current_password="Wrong-password-123")
    assert response.status_code == 403
    assert response.json() == {"detail": "Current password is incorrect."}
    with Session(app.state.engine) as session:
        assert session.get(Traveler, 1).password_hash == original
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_google_only_account_is_rejected(api):
    client, app, _ = api
    with Session(app.state.engine) as session:
        traveler = Traveler(name="Google user", email="google@example.com", sso_email="google@example.com",
                            password_hash="", auth_type="google")
        session.add(traveler)
        session.flush()
        active = AuthSession(id="google-session", traveler_id=traveler.id, refresh_hash="0" * 64,
                             expires_at=2**31)
        session.add(active)
        session.commit()
        token = access_token(active, app.state.auth_settings).access_token
    response = change(client, {"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Password change is unavailable for Google-only accounts."}


def test_new_password_must_differ(api):
    client, _, headers = api
    response = change(client, headers, new_password=OLD)
    assert response.status_code == 400
    assert response.json() == {"detail": "Choose a different new password."}
    assert client.post("/auth/login", json={"email": EMAIL, "password": OLD}).status_code == 200


@pytest.mark.parametrize("new_password", ["short", "x" * 73, "é" * 37])
def test_invalid_new_password_is_rejected(api, new_password):
    client, _, headers = api
    response = change(client, headers, new_password=new_password)
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])


def test_extra_fields_are_rejected(api):
    client, _, headers = api
    response = change(client, headers, role="admin")
    assert response.status_code == 422


def test_other_sessions_are_revoked_but_current_session_survives(api):
    client, _, first_headers = api
    first_cookie = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    second_login = client.post("/auth/login", json={"email": EMAIL, "password": OLD})
    second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}
    second_cookie = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, first_cookie, domain="testserver.local", path="/auth")
    assert change(client, first_headers).status_code == 204
    assert client.get("/auth/me", headers=first_headers).status_code == 200
    assert client.post("/auth/refresh").status_code == 200
    assert client.get("/auth/me", headers=second_headers).status_code == 401
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, second_cookie, domain="testserver.local", path="/auth")
    assert client.post("/auth/refresh").status_code == 401


def test_unauthenticated_request_is_rejected(api):
    client, _, _ = api
    response = change(client, {})
    assert response.status_code == 401
