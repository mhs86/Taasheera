from datetime import date, timedelta

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel

import migrate
from app.auth import access_token
from app.database import build_engine
from app.main import create_app
from app.models import AuthSession, Traveler, TravelerProfile
from app.schema import migration_config, schema_revision


FIELDS = [
    "surname", "given_names", "birth_date", "nationality", "phone", "address_line1",
    "address_line2", "address_city", "address_region", "address_postal_code", "address_country",
]


@pytest.fixture
def api(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'profile.db').as_posix()}")
    with TestClient(app) as client:
        headers = []
        with Session(app.state.engine) as session:
            for number in (1, 2):
                traveler = Traveler(name=f"Traveler {number}", email=f"traveler{number}@example.com",
                                    password_hash="test-hash")
                session.add(traveler)
                session.flush()
                auth_session = AuthSession(id=f"profile-session-{number}", traveler_id=traveler.id,
                                           refresh_hash=f"{number}" * 64, expires_at=2**31)
                session.add(auth_session)
                headers.append({"Authorization": f"Bearer {access_token(auth_session, app.state.auth_settings).access_token}"})
            session.commit()
        yield client, app, headers


def test_get_without_profile_returns_every_field_as_null(api):
    client, app, headers = api
    response = client.get("/profile", headers=headers[0])
    assert response.status_code == 200
    assert response.json() == {field: None for field in FIELDS}
    assert response.headers["cache-control"] == "private, no-store"
    with Session(app.state.engine) as session:
        assert session.get(TravelerProfile, 1) is None


def test_put_then_get_replaces_fields_and_normalizes_phone(api):
    client, app, headers = api
    original = {
        "surname": "Mansour", "given_names": "Lina", "birth_date": "1997-04-05",
        "nationality": "LBN", "phone": "+961 71 123 456",
        "address_line1": "Example street", "address_city": "Beirut", "address_country": "D",
    }
    result = client.put("/profile", headers=headers[0], json=original)
    assert result.status_code == 200
    assert result.json()["phone"] == "+96171123456"
    assert result.headers["cache-control"] == "private, no-store"
    assert client.get("/profile", headers=headers[0]).json() == result.json()
    replacement = client.put("/profile", headers=headers[0], json={
        "surname": "Mansour", "given_names": "", "address_line2": "", "address_region": "",
        "address_postal_code": "", "phone": "",
    })
    assert replacement.status_code == 200
    assert replacement.json() == {
        **{field: None for field in FIELDS}, "surname": "Mansour", "given_names": "",
        "address_line2": "", "address_region": "", "address_postal_code": "",
    }
    assert client.get("/profile", headers=headers[0]).json() == replacement.json()
    with Session(app.state.engine) as session:
        assert session.get(Traveler, 1).name == "Traveler 1"


@pytest.mark.parametrize("invalid", [
    {"birth_date": (date.today() + timedelta(days=1)).isoformat()},
    {"birth_date": date.today().isoformat()},
    {"birth_date": "2001-1-1"},
    {"surname": "x" * 101},
    {"surname": ""},
    {"given_names": "x" * 101},
    {"phone": "12345"},
    {"phone": "+999123456789"},
    {"nationality": "lbn"},
    {"nationality": "LBNX"},
    {"nationality": "L1N"},
    {"address_country": "deu"},
    {"address_country": "DEUX"},
    {"unknown": "value"},
])
def test_invalid_values_are_rejected_without_saving(api, invalid):
    client, app, headers = api
    response = client.put("/profile", headers=headers[0], json=invalid)
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    with Session(app.state.engine) as session:
        assert session.get(TravelerProfile, 1) is None


def test_unauthenticated_requests_are_rejected(api):
    client, _, _ = api
    assert client.get("/profile").status_code == 401
    assert client.put("/profile", json={"surname": "Example"}).status_code == 401


def test_travelers_can_only_read_and_replace_their_own_profile(api):
    client, app, headers = api
    assert client.put("/profile", headers=headers[0], json={"surname": "First"}).status_code == 200
    assert client.get("/profile", headers=headers[1]).json()["surname"] is None
    assert client.put("/profile", headers=headers[1], json={"surname": "Second"}).status_code == 200
    assert client.get("/profile", headers=headers[0]).json()["surname"] == "First"
    assert client.get("/profile", headers=headers[1]).json()["surname"] == "Second"
    with Session(app.state.engine) as session:
        assert session.get(TravelerProfile, 1).surname == "First"
        assert session.get(TravelerProfile, 2).surname == "Second"


def test_migration_upgrades_from_previous_head_without_changing_traveler(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'previous-head.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "c82a91f4d670")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id,name,email,password_hash,auth_type) "
                                "VALUES (1,'Existing','existing@example.com','hash','email_password')"))
    command.upgrade(migration_config(), "head")
    with Session(engine) as session:
        assert session.get(Traveler, 1).name == "Existing"
        session.add(TravelerProfile(traveler_id=1, surname="Existing"))
        session.commit()
        assert session.get(TravelerProfile, 1).surname == "Existing"
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
        assert inspect(connection).get_pk_constraint("travelerprofile")["constrained_columns"] == ["traveler_id"]
        assert inspect(connection).get_foreign_keys("travelerprofile")[0]["referred_table"] == "traveler"
    assert schema_revision(engine)[0] == schema_revision(engine)[1]
    engine.dispose()


def test_unversioned_previous_schema_can_be_adopted(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'unversioned-profile.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "c82a91f4d670")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    migrate.upgrade()
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
    assert schema_revision(engine)[0] == schema_revision(engine)[1]
    engine.dispose()
