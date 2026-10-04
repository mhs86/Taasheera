import io
import json
import logging

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel

import migrate
from app.database import build_engine
from app.main import create_app
from app.models import ActivityEvent, Traveler
from app.observability import RequestJsonFormatter, request_log
from app.schema import migration_config, schema_revision


def database_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'deploy.db').as_posix()}"


def test_fresh_migration_is_required_before_api_start_and_health_checks_it(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SCHEMA_AUTO_CREATE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://travel.example")
    app = create_app()
    with pytest.raises(RuntimeError, match="migrate.py upgrade"):
        with TestClient(app):
            pass

    migrate.upgrade()
    engine = build_engine(url)
    try:
        current, head = schema_revision(engine)
        assert current == head
        assert {"traveler", "activityevent", "alembic_version"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    with TestClient(create_app()) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ok"}


def test_existing_local_schema_is_stamped_without_losing_data(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Traveler(name="Maya", email="maya@example.com", password_hash="existing-hash"))
        session.commit()
    engine.dispose()

    migrate.upgrade()
    migrate.upgrade()  # Repeating the release step is safe.
    engine = build_engine(url)
    try:
        with Session(engine) as session:
            assert session.get(Traveler, 1).email == "maya@example.com"
        assert schema_revision(engine)[0] == schema_revision(engine)[1]
    finally:
        engine.dispose()


def test_unversioned_schema_drift_is_not_silently_stamped(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    SQLModel.metadata.create_all(engine)
    ActivityEvent.__table__.drop(engine)
    engine.dispose()
    with pytest.raises(RuntimeError, match="differs"):
        migrate.upgrade()
    engine = build_engine(url)
    try:
        assert schema_revision(engine)[0] is None
    finally:
        engine.dispose()


def test_initial_downgrade_refuses_to_drop_traveler_data(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    migrate.upgrade()
    with pytest.raises(RuntimeError, match="cannot be downgraded"):
        command.downgrade(migration_config(), "base")
    engine = build_engine(url)
    try:
        assert "traveler" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_readiness_fails_without_required_ocr_but_liveness_stays_up(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIRE_TESSERACT", "true")
    monkeypatch.setattr("app.main.shutil.which", lambda name: None)
    app = create_app(database_url(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "Service is not ready."}


@pytest.mark.parametrize("name", ["SCHEMA_AUTO_CREATE", "REQUIRE_TESSERACT"])
def test_invalid_runtime_boolean_fails_startup(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "maybe")
    with pytest.raises(RuntimeError, match=name):
        with TestClient(create_app(database_url(tmp_path))):
            pass


@pytest.mark.parametrize("setting,value,error", [
    ("SCHEMA_AUTO_CREATE", "true", "SCHEMA_AUTO_CREATE"),
    ("AUTH_COOKIE_SECURE", "false", "AUTH_COOKIE_SECURE"),
    ("AUTH_ALLOWED_ORIGINS", "http://travel.example", "AUTH_ALLOWED_ORIGINS"),
    ("DATABASE_URL", "", "DATABASE_URL"),
])
def test_production_rejects_unsafe_configuration(tmp_path, monkeypatch, setting, value, error):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEMA_AUTO_CREATE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("DATABASE_URL", database_url(tmp_path))
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://travel.example")
    monkeypatch.setenv(setting, value)
    with pytest.raises(RuntimeError, match=error):
        with TestClient(create_app(database_url(tmp_path))):
            pass


def test_request_logs_use_route_templates_and_exclude_sensitive_input(tmp_path):
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RequestJsonFormatter())
    request_log.addHandler(handler)
    try:
        with TestClient(create_app(database_url(tmp_path))) as client:
            live = client.get("/health/live")
            assert live.status_code == 200
            assert len(live.headers["x-request-id"]) == 32
            response = client.post("/auth/register", json={
                "name": "Sensitive Name", "email": "private@example.com",
                "password": "private-password-123",
            })
            assert response.status_code == 201
            assert client.post("/passports/private-upload-id/extract").status_code == 401
    finally:
        request_log.removeHandler(handler)
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [(record["route"], record["status"]) for record in records] == [
        ("/health/live", 200), ("/auth/register", 201),
        ("/passports/{upload_id}/extract", 401),
    ]
    assert all(set(record) == {"request_id", "method", "route", "status", "duration_ms"}
               for record in records)
    for secret in ("private-password-123", "private@example.com", "Sensitive Name", "private-upload-id"):
        assert secret not in output.getvalue()
