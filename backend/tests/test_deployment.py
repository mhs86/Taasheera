import io
import json
import logging
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import DefaultClause, MetaData, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

import migrate
from app.database import build_engine
from app.main import create_app
from app.models import ROLES, STATUSES, ActivityEvent, Traveler
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
            maya = session.get(Traveler, 1)
            assert maya.email == "maya@example.com"
            assert (maya.role, maya.status) == ("traveler", "active")
        assert schema_revision(engine)[0] == schema_revision(engine)[1]
    finally:
        engine.dispose()


def traveler_rows(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT * FROM traveler ORDER BY id")).mappings().all()


def check_names(engine, table="traveler"):
    return {check["name"] for check in inspect(engine).get_check_constraints(table)}


TRAVELER_CHECKS = {"ck_traveler_auth_type", "ck_traveler_role", "ck_traveler_status"}
ROLE_PARENT_REVISION = "e6f81a73c902"  # The revision before roles; downgrading also removes the later application tables.


HASH = "$2b$12$" + "x" * 53  # The shape of a bcrypt hash; never checked against a password here.


def test_sprint1_database_is_adopted_at_the_initial_revision_and_upgraded(sprint1_database, capsys):
    engine = build_engine(sprint1_database)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO traveler (id, name, email, password_hash) VALUES "
            "(1, 'Maya', 'maya@example.com', :hash), (2, 'Omar', 'omar@example.com', '')"
        ), {"hash": HASH})
        connection.execute(text("INSERT INTO googleidentity (subject, traveler_id) VALUES ('google-subject-2', 2)"))
        connection.execute(text(
            "INSERT INTO activityevent (traveler_id, occurred_at, event_type, identifier, outcome) "
            "VALUES (1, '2026-10-01 10:00:00.000000', 'sign_in', 'email_password', 'success')"
        ))
    engine.dispose()

    migrate.upgrade()
    assert "Adopted existing schema at the current revision." in capsys.readouterr().out
    engine = build_engine(sprint1_database)
    try:
        current, head = schema_revision(engine)
        assert current == head != migrate.BASELINE_REVISION
        rows = traveler_rows(engine)
        assert [(row["id"], row["email"], row["role"], row["status"]) for row in rows] == [
            (1, "maya@example.com", "traveler", "active"), (2, "omar@example.com", "traveler", "active"),
        ]
        assert [row["password_hash"] for row in rows] == [HASH, ""]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT subject, traveler_id FROM googleidentity")).all() == [
                ("google-subject-2", 2)]
            assert connection.execute(text("SELECT traveler_id, event_type FROM activityevent")).all() == [
                (1, "sign_in")]
            assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
        assert check_names(engine) == TRAVELER_CHECKS
        assert [row["auth_type"] for row in rows] == ["email_password", "google"]
    finally:
        engine.dispose()

    migrate.upgrade()
    assert "Database migrations are current." in capsys.readouterr().out


@pytest.mark.parametrize("drift", [
    "CREATE TABLE application (id INTEGER PRIMARY KEY)",
    "ALTER TABLE traveler ADD COLUMN nickname VARCHAR(40)",
    "DROP INDEX ix_traveler_email",
    "ALTER TABLE traveler ADD COLUMN role VARCHAR(20)",
])
def test_sprint1_database_with_drift_is_refused_and_left_untouched(sprint1_database, drift):
    engine = build_engine(sprint1_database)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO traveler (id, name, email, password_hash) VALUES (1, 'Maya', 'maya@example.com', 'hash')"
        ))
        connection.execute(text(drift))
    columns = [column["name"] for column in inspect(engine).get_columns("traveler")]
    engine.dispose()

    with pytest.raises(RuntimeError, match="differs"):
        migrate.upgrade()
    engine = build_engine(sprint1_database)
    try:
        assert schema_revision(engine)[0] is None
        assert [column["name"] for column in inspect(engine).get_columns("traveler")] == columns
        assert [(row["id"], row["email"]) for row in traveler_rows(engine)] == [(1, "maya@example.com")]
        assert check_names(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.parametrize("columns", [
    ("role VARCHAR(20) NOT NULL DEFAULT 'traveler'", "status VARCHAR(20) NOT NULL DEFAULT 'active'"),
    ("role VARCHAR(20) NOT NULL DEFAULT 'admin'", "status VARCHAR(20) NOT NULL DEFAULT 'active'"),
])
def test_unversioned_role_columns_without_the_checks_or_defaults_are_refused(sprint1_database, columns):
    # Same columns as the models, but missing the CHECK guards or defaulting to another role.
    engine = build_engine(sprint1_database)
    with engine.begin() as connection:
        for column in columns:
            connection.execute(text(f"ALTER TABLE traveler ADD COLUMN {column}"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="differs"):
        migrate.upgrade()
    engine = build_engine(sprint1_database)
    try:
        assert schema_revision(engine)[0] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("change", ["without_role_checks", "admin_default"])
def test_current_schema_with_weaker_role_guards_is_not_stamped(tmp_path, monkeypatch, change):
    # Same tables and columns as the models, so only the CHECK and default comparisons can catch it.
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    weaker = MetaData()
    for table in SQLModel.metadata.sorted_tables:
        table.to_metadata(weaker)
    traveler = weaker.tables["traveler"]
    if change == "without_role_checks":
        traveler.constraints = {constraint for constraint in traveler.constraints
                                if constraint.name not in {"ck_traveler_role", "ck_traveler_status"}}
    else:
        traveler.c.role.server_default = DefaultClause("admin")
    engine = build_engine(url)
    weaker.create_all(engine)
    engine.dispose()
    with pytest.raises(RuntimeError, match="differs"):
        migrate.upgrade()
    engine = build_engine(url)
    try:
        assert schema_revision(engine)[0] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("start", ["sprint1", "initial_revision"])
@pytest.mark.parametrize("interrupted_at", [
    "CREATE TABLE _alembic_tmp_traveler", "DROP TABLE traveler",
    "ALTER TABLE _alembic_tmp_traveler", "UPDATE alembic_version",
])
def test_interrupted_sqlite_upgrade_rolls_back_completely(tmp_path, monkeypatch, start, interrupted_at):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    with engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, migrate.BASELINE_REVISION)
        if start == "sprint1":
            connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text(
            "INSERT INTO traveler (id, name, email, password_hash) VALUES (1, 'Maya', 'maya@example.com', 'hash')"
        ))
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    real_build_engine = migrate.build_engine

    def failing_engine(*args, **kwargs):
        target = real_build_engine(*args, **kwargs)

        @event.listens_for(target, "before_cursor_execute")
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().startswith(interrupted_at):
                raise RuntimeError("interrupted")

        return target

    monkeypatch.setattr(migrate, "build_engine", failing_engine)
    with pytest.raises(RuntimeError, match="interrupted"):
        migrate.upgrade()
    monkeypatch.setattr(migrate, "build_engine", real_build_engine)

    engine = build_engine(url)
    try:
        assert schema_revision(engine)[0] == (None if start == "sprint1" else migrate.BASELINE_REVISION)
        assert set(inspect(engine).get_table_names()) == tables
        assert [(row["id"], row["email"]) for row in traveler_rows(engine)] == [(1, "maya@example.com")]
        migrate.upgrade()  # Nothing half-applied is left to block a retry.
        assert schema_revision(engine)[0] == schema_revision(engine)[1]
        assert [(row["id"], row["role"]) for row in traveler_rows(engine)] == [(1, "traveler")]
    finally:
        engine.dispose()


def test_pre_sprint1_hand_made_traveler_table_is_refused(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE traveler (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "email VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(60) NOT NULL)"
        ))
        connection.execute(text("INSERT INTO traveler VALUES (7, 'Existing', 'existing@example.com', 'hash')"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="differs"):
        migrate.upgrade()
    engine = build_engine(url)
    try:
        assert schema_revision(engine)[0] is None
        assert set(inspect(engine).get_table_names()) == {"traveler"}
        assert [row["id"] for row in traveler_rows(engine)] == [7]
    finally:
        engine.dispose()


def test_migrated_schema_matches_models_including_defaults_and_checks(tmp_path, monkeypatch):
    migrated_url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    migrate.upgrade()
    migrated = build_engine(migrated_url)
    created = build_engine(f"sqlite:///{(tmp_path / 'created.db').as_posix()}")
    SQLModel.metadata.create_all(created)

    def traveler_shape(engine):
        inspector = inspect(engine)
        # Migrations append columns while create_all follows the model, so compare them unordered.
        columns = sorted((column["name"], str(column["type"]), column["nullable"], column["default"])
                         for column in inspector.get_columns("traveler"))
        checks = sorted((check["name"], check["sqltext"]) for check in inspector.get_check_constraints("traveler"))
        indexes = sorted((index["name"], tuple(index["column_names"]), bool(index["unique"]))
                         for index in inspector.get_indexes("traveler"))
        return columns, checks, indexes

    try:
        with migrated.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
        # alembic check ignores server defaults and CHECK constraints, so compare them directly.
        assert traveler_shape(migrated) == traveler_shape(created)
        columns, checks, _ = traveler_shape(migrated)
        assert ("role", "VARCHAR(20)", False, "'traveler'") in columns
        assert ("status", "VARCHAR(20)", False, "'active'") in columns
        assert {name for name, _ in checks} == TRAVELER_CHECKS
    finally:
        migrated.dispose()
        created.dispose()


@pytest.fixture(params=["create_all", "migrated"])
def schema_engine(request, tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    if request.param == "migrated":
        migrate.upgrade()
    engine = build_engine(url)
    if request.param == "create_all":
        SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_database_rejects_unknown_roles_and_statuses(schema_engine):
    insert = text("INSERT INTO traveler (name, email, password_hash, auth_type, role, status) "
                  "VALUES ('Test', :email, 'hash', 'email_password', :role, :status)")
    accepted = [(role, "active") for role in ROLES] + [("traveler", status) for status in STATUSES]
    for index, (role, status) in enumerate(accepted):
        with schema_engine.begin() as connection:
            connection.execute(insert, {"email": f"ok{index}@example.com", "role": role, "status": status})
    rejected = [(role, "active") for role in ("Admin", " admin", "admin ", "ADMIN", "superuser", "")]
    rejected += [("traveler", status) for status in ("Active", "banned", "")]
    for role, status in rejected:
        with pytest.raises(IntegrityError):
            with schema_engine.begin() as connection:
                connection.execute(insert, {"email": "bad@example.com", "role": role, "status": status})
    # SQLModel table models skip validation, so the database constraint is the real guard.
    with Session(schema_engine) as session:
        session.add(Traveler(name="Test", email="orm@example.com", password_hash="hash", role="Admin"))
        with pytest.raises(IntegrityError):
            session.commit()
    with schema_engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (name, email, password_hash, auth_type) "
                                "VALUES ('Old code', 'old@example.com', 'hash', 'email_password')"))
        assert connection.execute(text(
            "SELECT role, status FROM traveler WHERE email = 'old@example.com'"
        )).one() == ("traveler", "active")
        assert connection.execute(text("SELECT count(*) FROM traveler")).scalar_one() == len(accepted) + 1


def test_role_revision_downgrades_to_the_previous_revision_and_back(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    migrate.upgrade()
    engine = build_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO traveler (id, name, email, password_hash, auth_type, role) "
                                    "VALUES (1, 'Maya', 'maya@example.com', 'hash', 'email_password', 'admin')"))
        command.downgrade(migration_config(), ROLE_PARENT_REVISION)
        columns = {column["name"] for column in inspect(engine).get_columns("traveler")}
        assert not {"role", "status"} & columns and {"auth_type", "sso_email", "last_login_at"} <= columns
        assert check_names(engine) == {"ck_traveler_auth_type"}
        assert "admin_user_auth" in inspect(engine).get_view_names()
        assert [(row["id"], row["email"]) for row in traveler_rows(engine)] == [(1, "maya@example.com")]
        assert schema_revision(engine)[0] == ROLE_PARENT_REVISION

        command.upgrade(migration_config(), "head")
        # Role assignments do not survive a downgrade; they must be made again.
        assert [(row["id"], row["role"], row["status"]) for row in traveler_rows(engine)] == [
            (1, "traveler", "active")]
        assert check_names(engine) == TRAVELER_CHECKS
        assert "admin_user_auth" in inspect(engine).get_view_names()
    finally:
        engine.dispose()


CREATED_AT_PARENT_REVISION = "1a1ce7fbb089"  # The revision before traveler.created_at.


def test_created_at_is_backfilled_from_registration_events_and_downgrades(tmp_path, monkeypatch):
    url = database_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    engine = build_engine(url)
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, CREATED_AT_PARENT_REVISION)
            connection.execute(text(
                "INSERT INTO traveler (id, name, email, password_hash, auth_type) VALUES "
                "(1, 'Maya', 'maya@example.com', 'hash', 'email_password'), "
                "(2, 'Omar', 'omar@example.com', 'hash', 'email_password')"
            ))
            connection.execute(text(
                "INSERT INTO activityevent (traveler_id, occurred_at, event_type, identifier, outcome) VALUES "
                "(1, '2026-10-02 09:00:00.000000', 'sign_in', 'email_password', 'success'), "
                "(1, '2026-10-03 10:00:00.000000', 'registration', 'email_password', 'success'), "
                "(1, '2026-10-05 10:00:00.000000', 'registration', 'google', 'success'), "
                "(2, '2026-10-04 10:00:00.000000', 'sign_in', 'email_password', 'success')"
            ))
        migrate.upgrade()
        with Session(engine) as session:
            maya, omar = session.get(Traveler, 1), session.get(Traveler, 2)
            # The earliest registration event, never another kind of event; no event leaves it unknown.
            assert maya.created_at == datetime(2026, 10, 3, 10, tzinfo=timezone.utc)
            assert omar.created_at is None

        command.downgrade(migration_config(), CREATED_AT_PARENT_REVISION)
        assert "created_at" not in {column["name"] for column in inspect(engine).get_columns("traveler")}
        assert check_names(engine) == TRAVELER_CHECKS
        assert "admin_user_auth" in inspect(engine).get_view_names()
        assert [row["email"] for row in traveler_rows(engine)] == ["maya@example.com", "omar@example.com"]
        command.upgrade(migration_config(), "head")
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
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id, name, email, password_hash, auth_type) "
                                "VALUES (1, 'Maya', 'maya@example.com', 'hash', 'email_password')"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="cannot be downgraded"):
        command.downgrade(migration_config(), "base")
    engine = build_engine(url)
    try:
        # SQLite DDL is not transactional: newer revisions are undone, the initial one refuses.
        assert schema_revision(engine)[0] == migrate.BASELINE_REVISION
        assert "traveler" in inspect(engine).get_table_names()
        assert [(row["id"], row["email"]) for row in traveler_rows(engine)] == [(1, "maya@example.com")]
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
