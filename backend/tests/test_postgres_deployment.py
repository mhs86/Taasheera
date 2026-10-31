"""Opt-in deployment smoke test against a disposable PostgreSQL database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, make_url, text
from sqlalchemy.exc import IntegrityError
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlmodel import SQLModel

import manage
import migrate
from app.database import build_engine, normalize_database_url
from app.main import create_app
from app.schema import migration_config, schema_revision


ROLE_PARENT_REVISION = "e6f81a73c902"  # The revision before roles; downgrading also removes the later application tables.


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_migrated_postgres_schema_has_no_model_drift(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    migrate.upgrade()
    engine = build_engine()
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), SQLModel.metadata) == []
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_migration_and_authenticated_request_on_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEMA_AUTO_CREATE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://travel.example")
    migrate.upgrade()
    email = f"ci-{uuid4().hex}@example.com"
    with TestClient(create_app(), base_url="https://testserver") as client:
        assert client.get("/health/ready").status_code == 200
        registered = client.post("/auth/register", json={
            "name": "CI traveler", "email": email, "password": "safe-test-password-123",
        })
        assert registered.status_code == 201
        login = client.post("/auth/login", json={
            "email": email, "password": "safe-test-password-123",
        })
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.post("/activity/events", headers=headers, json={
            "event_type": "page_visit", "page": "home", "outcome": "visited",
        }).status_code == 204


@pytest.mark.skipif(not os.environ.get('TEST_POSTGRES_URL'), reason='needs disposable PostgreSQL')
def test_postgres_otp_updates_account_and_revokes_sessions(monkeypatch):
    from unittest.mock import Mock
    from sqlalchemy import text
    from sqlmodel import Session
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_POSTGRES_URL'])
    monkeypatch.setenv('SCHEMA_AUTO_CREATE', 'false')
    monkeypatch.setenv('RESET_MAIL_PROVIDER', 'ses')
    monkeypatch.setenv('SES_FROM_EMAIL', 'sharafm032@gmail.com')
    migrate.upgrade()
    sender = Mock()
    email = f'otp-{uuid4().hex}@example.com'
    app = create_app(reset_sender=sender)
    with TestClient(app) as client:
        registered = client.post('/auth/register', json={'name': 'OTP specimen', 'email': email, 'password': 'Original-test-password'})
        assert registered.status_code == 201
        owner = registered.json()['id']
        access = client.post('/auth/login', json={'email': email, 'password': 'Original-test-password'}).json()['access_token']
        assert client.post('/auth/forgot-password', json={'email': email}).status_code == 202
        code = sender.send_reset.call_args.args[1]
        assert len(code) == 6 and code.isdigit()
        verified = client.post('/auth/verify-reset-code', json={'email': email, 'code': code})
        assert verified.status_code == 200
        grant = verified.json()['reset_token']
        assert client.post('/auth/verify-reset-code', json={'email': email, 'code': code}).status_code == 400
        assert client.post('/auth/reset-password', json={'token': grant, 'password': 'Replacement-test-password'}).status_code == 204
        assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + access}).status_code == 401
        assert client.post('/auth/login', json={'email': email, 'password': 'Original-test-password'}).status_code == 401
        assert client.post('/auth/login', json={'email': email, 'password': 'Replacement-test-password'}).status_code == 200
        with Session(app.state.engine) as session:
            report = session.execute(text('SELECT auth_type,password_enabled FROM admin_user_auth WHERE id=:id'), {'id': owner}).one()
            assert tuple(report) == ('email_password', 1)


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_role_revision_round_trip_and_checks_on_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    migrate.upgrade()
    email = f"ci-{uuid4().hex}@example.com"
    engine = build_engine()
    try:
        try:
            command.downgrade(migration_config(), ROLE_PARENT_REVISION)
            assert schema_revision(engine)[0] == ROLE_PARENT_REVISION
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO traveler (name, email, password_hash, auth_type) "
                                        "VALUES ('CI traveler', :email, '', 'google')"), {"email": email})
        finally:
            # CI runs alembic check against this database afterwards, so always end at head.
            command.upgrade(migration_config(), "head")
        current, head = schema_revision(engine)
        assert current == head
        with engine.connect() as connection:
            assert connection.execute(text("SELECT role, status FROM traveler WHERE email = :email"),
                                      {"email": email}).one() == ("traveler", "active")
        for change in ("role = 'Admin'", "status = 'banned'"):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text(f"UPDATE traveler SET {change} WHERE email = :email"), {"email": email})
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_unversioned_sprint1_schema_is_adopted_and_upgraded_on_postgres(monkeypatch):
    # A throwaway database, so the shared CI database stays at head for alembic check.
    server_url = make_url(normalize_database_url(os.environ["TEST_POSTGRES_URL"]))
    name = f"ci_sprint1_{uuid4().hex[:12]}"
    server = build_engine(server_url.render_as_string(hide_password=False)).execution_options(
        isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server_url.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, migrate.BASELINE_REVISION)
            connection.execute(text("DROP TABLE alembic_version"))
            connection.execute(text("INSERT INTO traveler (id, name, email, password_hash) VALUES "
                                    "(1, 'Maya', 'maya@example.com', 'hash'), (2, 'Omar', 'omar@example.com', '')"))
        migrate.upgrade()
        current, head = schema_revision(engine)
        assert current == head
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT id, auth_type, role, status FROM traveler ORDER BY id"
            )).all() == [(1, "email_password", "traveler", "active"), (2, "google", "traveler", "active")]
            assert connection.execute(text("SELECT count(*) FROM admin_user_auth")).scalar_one() == 2
        assert {check["name"] for check in inspect(engine).get_check_constraints("traveler")} == {
            "ck_traveler_auth_type", "ck_traveler_role", "ck_traveler_status"}
    finally:
        engine.dispose()
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        server.dispose()


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_admin_gate_and_role_command_on_postgres(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEMA_AUTO_CREATE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://travel.example")
    migrate.upgrade()
    email = f"ci-{uuid4().hex}@example.com"
    with TestClient(create_app(), base_url="https://testserver") as client:
        assert client.post("/auth/register", json={
            "name": "CI staff", "email": email, "password": "safe-test-password-123",
        }).status_code == 201
        login = client.post("/auth/login", json={"email": email, "password": "safe-test-password-123"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/admin/me", headers=headers).status_code == 403
        manage.main(["set-role", "--email", email, "--role", "admin"])
        promoted = client.get("/admin/me", headers=headers)
        assert promoted.status_code == 200 and promoted.json()["role"] == "admin"
        manage.main(["set-role", "--email", email, "--role", "traveler"])
        assert client.get("/admin/me", headers=headers).status_code == 403
    output = capsys.readouterr().out
    assert "role changed from traveler to admin." in output and email not in output


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_concurrent_role_changes_keep_an_accurate_audit_trail_on_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    migrate.upgrade()
    email = f"ci-{uuid4().hex}@example.com"
    engine = build_engine()
    try:
        with engine.begin() as connection:
            traveler_id = connection.execute(text(
                "INSERT INTO traveler (name, email, password_hash, auth_type) VALUES ('CI staff', :email, '', 'google') RETURNING id"
            ), {"email": email}).scalar_one()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda role: manage.set_role(email, role), ["admin", "support", "traveler"] * 4))
        with engine.connect() as connection:
            final = connection.execute(text("SELECT role FROM traveler WHERE id = :id"), {"id": traveler_id}).scalar_one()
            changes = [identifier.removeprefix("cli:").split("->") for identifier in connection.execute(text(
                "SELECT identifier FROM activityevent WHERE traveler_id = :id AND event_type = 'role_change' ORDER BY id"
            ), {"id": traveler_id}).scalars()]
        # The row lock makes every change start from the role the previous change left.
        assert changes and changes[0][0] == "traveler" and changes[-1][1] == final
        assert all(earlier[1] == later[0] for earlier, later in zip(changes, changes[1:]))
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_role_command_reports_an_unreachable_database_without_details(monkeypatch):
    url = make_url(normalize_database_url(os.environ["TEST_POSTGRES_URL"])).set(database="taasheera_missing_db")
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    with pytest.raises(SystemExit) as refused:
        manage.set_role("ci@example.com", "admin")
    assert refused.value.code == "Could not connect to the database. Check DATABASE_URL."


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_admin_user_management_on_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://travel.example")
    migrate.upgrade()
    tag = uuid4().hex[:12]
    password = "safe-test-password-123"
    origin = {"Origin": "https://travel.example"}
    emails = {key: f"ci-{key}-{tag}@example.com" for key in ("first", "second", "member")}
    engine = build_engine()

    def sign_in(client, key):
        client.cookies.clear()
        response = client.post("/auth/login", json={"email": emails[key], "password": password}, headers=origin)
        client.cookies.clear()
        return response

    try:
        with TestClient(create_app()) as one, TestClient(create_app()) as two:
            ids = {}
            for key, name in (("first", "CI admin one"), ("second", "CI admin two"), ("member", f"CI 100%_{tag}")):
                created = one.post("/auth/register", json={"name": name, "email": emails[key], "password": password},
                                   headers=origin)
                assert created.status_code == 201
                ids[key] = created.json()["id"]
            for key in ("first", "second"):
                manage.set_role(emails[key], "admin")
            headers = {key: {"Authorization": f"Bearer {sign_in(one, key).json()['access_token']}", **origin}
                       for key in ("first", "second")}
            member_token = sign_in(one, "member").json()["access_token"]

            # Escaped search: % and _ are literal, and only this run's member matches.
            found = one.get("/admin/users", params={"q": f"100%_{tag}"}, headers=headers["first"]).json()
            assert [item["id"] for item in found["items"]] == [ids["member"]]

            assert one.post(f"/admin/users/{ids['member']}/suspend", headers=headers["first"]).status_code == 200
            assert one.get("/auth/me", headers={"Authorization": f"Bearer {member_token}"}).status_code == 401
            refused = sign_in(one, "member")
            assert refused.status_code == 403 and refused.json()["detail"]["code"] == "account_suspended"

            overview = one.get("/admin/overview", headers=headers["first"]).json()
            with engine.connect() as connection:
                total, recent, suspended = connection.execute(text(
                    "SELECT count(*), count(*) FILTER (WHERE created_at >= now() - interval '7 days'), "
                    "count(*) FILTER (WHERE status = 'suspended') FROM traveler")).one()
                applications = connection.execute(text("SELECT count(*) FROM application")).scalar_one()
            assert overview == {"total_users": total, "new_last_7_days": recent, "suspended": suspended,
                                "applications_started": applications}
            assert recent >= 3

            # Two admins demote each other at the same moment: the row locks let exactly one win.
            for _ in range(5):
                barrier = Barrier(2)

                def demote(client, actor, target):
                    barrier.wait()
                    return client.put(f"/admin/users/{ids[target]}/role", json={"role": "traveler"},
                                      headers=headers[actor]).status_code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = sorted(pool.map(lambda job: demote(*job), [(one, "first", "second"),
                                                                         (two, "second", "first")]))
                assert results == [200, 403]
                with engine.connect() as connection:
                    roles = connection.execute(text("SELECT role FROM traveler WHERE id IN (:a, :b)"),
                                               {"a": ids["first"], "b": ids["second"]}).scalars().all()
                assert sorted(roles) == ["admin", "traveler"]
                with engine.begin() as connection:
                    connection.execute(text("UPDATE traveler SET role = 'admin' WHERE id IN (:a, :b)"),
                                       {"a": ids["first"], "b": ids["second"]})
    finally:
        engine.dispose()
