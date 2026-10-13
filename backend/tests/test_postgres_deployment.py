"""Opt-in deployment smoke test against a disposable PostgreSQL database."""

import os
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.exc import IntegrityError

import migrate
from app.database import build_engine, normalize_database_url
from app.main import create_app
from app.schema import migration_config, schema_revision


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


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_role_revision_round_trip_and_checks_on_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    migrate.upgrade()
    email = f"ci-{uuid4().hex}@example.com"
    engine = build_engine()
    try:
        try:
            command.downgrade(migration_config(), migrate.BASELINE_REVISION)
            assert schema_revision(engine)[0] == migrate.BASELINE_REVISION
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO traveler (name, email, password_hash) "
                                        "VALUES ('CI traveler', :email, '')"), {"email": email})
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
def test_unversioned_sprint1_schema_is_refused_on_postgres(monkeypatch):
    # Adopting a Sprint 1 schema is only for local SQLite files; PostgreSQL was always migrated.
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
        with pytest.raises(RuntimeError, match="differs from the current models. Back it up"):
            migrate.upgrade()
        assert schema_revision(engine)[0] is None
    finally:
        engine.dispose()
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        server.dispose()
