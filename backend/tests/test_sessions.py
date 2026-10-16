import time

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.auth import COOKIE_NAME, device_label
from app.database import build_engine
from app.main import create_app
from app.models import AuthSession
from app.schema import migration_config, schema_revision

PASSWORD = "Traveler-password-123"


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def login(client, email, agent):
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"User-Agent": agent})
    assert response.status_code == 200
    return bearer(response), client.cookies.get(COOKIE_NAME)


def use_cookie(client, raw):
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, raw, domain="testserver.local", path="/auth")


def test_device_label_only_recognizes_known_browser_and_system():
    assert device_label("Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/125.0 Safari/537.36") == "Chrome on Windows"
    assert device_label("Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit Chrome/125.0 Safari/537.36 Edg/125.0") == "Edge on macOS"
    assert device_label("private-client/1.0 (secret@example.com)") == "Unknown device"


def test_session_list_termination_and_immediate_refusal(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'sessions.db').as_posix()}")
    with TestClient(app) as client:
        for email in ("first@example.com", "second@example.com"):
            assert client.post("/auth/register", json={
                "name": "Traveler", "email": email, "password": PASSWORD,
            }).status_code == 201

        first, first_cookie = login(client, "first@example.com", "Mozilla/5.0 (Windows NT 10.0) Chrome/125.0")
        client.cookies.clear()
        second, second_cookie = login(client, "first@example.com", "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/605.1")
        client.cookies.clear()
        outsider, _ = login(client, "second@example.com", "private-client/1.0")

        listed = client.get("/sessions", headers=first)
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "private, no-store"
        rows = listed.json()
        assert len(rows) == 2
        assert all(set(row) == {"id", "device_label", "created_at", "last_active_at", "current"} for row in rows)
        assert {row["device_label"] for row in rows} == {"Chrome on Windows", "Safari on macOS"}
        assert sum(row["current"] for row in rows) == 1
        assert all(row["created_at"].endswith("Z") and row["last_active_at"].endswith("Z") for row in rows)
        current_id = next(row["id"] for row in rows if row["current"])
        other_id = next(row["id"] for row in rows if not row["current"])
        outsider_id = client.get("/sessions", headers=outsider).json()[0]["id"]

        assert client.delete(f"/sessions/{outsider_id}", headers=first).status_code == 404
        assert client.delete("/sessions/unknown", headers=first).status_code == 404
        current_response = client.delete(f"/sessions/{current_id}", headers=first)
        assert current_response.status_code == 400
        assert "logout" in current_response.json()["detail"].lower()
        assert client.get("/auth/me", headers=first).status_code == 200

        use_cookie(client, second_cookie)
        with Session(app.state.engine) as session:
            old_active = session.get(AuthSession, other_id).last_active_at
        assert client.post("/auth/refresh").status_code == 200
        with Session(app.state.engine) as session:
            assert session.get(AuthSession, other_id).last_active_at >= old_active

        ended = client.delete(f"/sessions/{other_id}", headers=first)
        assert ended.status_code == 204
        assert ended.headers["cache-control"] == "private, no-store"
        assert client.get("/auth/me", headers=second).status_code == 401
        assert client.post("/auth/refresh").status_code == 401
        assert len(client.get("/sessions", headers=first).json()) == 1
        assert client.get("/auth/me", headers=outsider).status_code == 200

        # Legacy rows have no fabricated timestamps or device metadata.
        with Session(app.state.engine) as session:
            legacy = AuthSession(id="legacy", traveler_id=1, refresh_hash="0" * 64,
                                 expires_at=int(time.time()) + 3600)
            expired = AuthSession(id="expired", traveler_id=1, refresh_hash="1" * 64,
                                  expires_at=int(time.time()) - 1)
            revoked = AuthSession(id="revoked", traveler_id=1, refresh_hash="2" * 64,
                                  expires_at=int(time.time()) + 3600, revoked=True)
            session.add_all([legacy, expired, revoked])
            session.commit()
        rows = client.get("/sessions", headers=first).json()
        assert {row["id"] for row in rows} == {current_id, "legacy"}
        legacy_row = next(row for row in rows if row["id"] == "legacy")
        assert legacy_row["device_label"] == "Unknown device"
        assert legacy_row["created_at"] is None and legacy_row["last_active_at"] is None
        assert client.delete("/sessions/expired", headers=first).status_code == 404
        assert client.delete("/sessions/revoked", headers=first).status_code == 404

        client.cookies.clear()
        third, third_cookie = login(client, "first@example.com", "Mozilla/5.0 (Android) Firefox/125.0")
        result = client.post("/sessions/revoke-others", headers=first)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "private, no-store"
        assert result.json() == {"ended": 3}  # legacy + third + an unrevoked, already-expired row
        assert client.get("/auth/me", headers=first).status_code == 200
        assert client.get("/auth/me", headers=third).status_code == 401
        use_cookie(client, third_cookie)
        assert client.post("/auth/refresh").status_code == 401
        use_cookie(client, first_cookie)
        assert client.post("/auth/refresh").status_code == 200
        assert client.get("/auth/me", headers=outsider).status_code == 200


def test_sessions_require_authentication_and_allowed_origin(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    with TestClient(app) as client:
        assert client.get("/sessions").status_code == 401
        assert client.delete("/sessions/unknown").status_code == 401
        assert client.post("/sessions/revoke-others").status_code == 401
        client.post("/auth/register", json={"name": "Traveler", "email": "first@example.com", "password": PASSWORD})
        headers, _ = login(client, "first@example.com", "private-client")
        blocked = {**headers, "Origin": "https://untrusted.example"}
        assert client.delete("/sessions/unknown", headers=blocked).status_code == 403
        assert client.post("/sessions/revoke-others", headers=blocked).status_code == 403


def test_migration_preserves_old_session_with_null_metadata(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'previous-head.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "d37a5b1e9c42")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id,name,email,password_hash,auth_type) "
                                "VALUES (1,'Existing','existing@example.com','hash','email_password')"))
        connection.execute(text("INSERT INTO authsession (id,traveler_id,refresh_hash,expires_at,revoked) "
                                "VALUES ('existing',1,:hash,:expiry,false)"),
                           {"hash": "0" * 64, "expiry": int(time.time()) + 3600})
    command.upgrade(migration_config(), "head")
    with Session(engine) as session:
        old = session.exec(select(AuthSession).where(AuthSession.id == "existing")).one()
        assert old.device_label is None and old.created_at is None and old.last_active_at is None
    assert {"device_label", "created_at", "last_active_at"} <= {
        column["name"] for column in inspect(engine).get_columns("authsession")
    }
    assert schema_revision(engine)[0] == schema_revision(engine)[1]
    engine.dispose()
