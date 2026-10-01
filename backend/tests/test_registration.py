import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.main import create_app
from app.models import Traveler


@pytest.fixture
def api(tmp_path):
    # Each test gets its own database, never the developer's database.
    app = create_app(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with TestClient(app) as client:
        yield client, app.state.engine


def registration(**changes):
    return {"name": "  Maya Haddad  ", "email": "Maya@Example.com", "password": "Travel-pass-123", **changes}


def test_registration_persists_only_bcrypt_hash_and_returns_public_details(api):
    client, engine = api
    response = client.post("/auth/register", json=registration())

    assert response.status_code == 201
    assert response.json() == {"id": 1, "name": "Maya Haddad", "email": "maya@example.com"}
    with Session(engine) as session:
        traveler = session.exec(select(Traveler)).one()
        assert traveler.password_hash != registration()["password"]
        assert bcrypt.checkpw(registration()["password"].encode(), traveler.password_hash.encode())
        assert not bcrypt.checkpw(b"wrong-password", traveler.password_hash.encode())
        assert traveler.password_hash.startswith("$2b$12$")


@pytest.mark.parametrize("email", ["maya@example.com", "MAYA@EXAMPLE.COM", " maya@example.com "])
def test_duplicate_email_is_rejected_without_changing_existing_user(api, email):
    client, engine = api
    assert client.post("/auth/register", json=registration()).status_code == 201
    response = client.post("/auth/register", json=registration(email=email, name="Someone else"))

    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered."}
    with Session(engine) as session:
        assert session.exec(select(Traveler)).one().name == "Maya Haddad"


def test_database_enforces_unique_email(api):
    client, engine = api
    client.post("/auth/register", json=registration())
    with Session(engine) as session:
        existing = session.exec(select(Traveler)).one()
        session.add(Traveler(name="Duplicate", email=existing.email, password_hash=existing.password_hash))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert len(session.exec(select(Traveler)).all()) == 1


@pytest.mark.parametrize("changes", [
    {"name": "   "},
    {"name": "a" * 101},
    {"email": "not-an-email"},
    {"password": "x9!z"},  # Avoid matching the standard validation code "too_short".
    {"password": "a" * 73},
    {"password": "é" * 37},
    {"password": None},
    {"role": "admin"},
    {"id": 99},
])
def test_invalid_input_is_rejected_without_echoing_password_or_saving_user(api, changes):
    client, engine = api
    payload = registration(**changes)
    response = client.post("/auth/register", json=payload)

    assert response.status_code == 422
    if payload["password"]:
        assert payload["password"] not in response.text
    assert all(set(error) == {"loc", "msg", "type"} for error in response.json()["detail"])
    with Session(engine) as session:
        assert session.exec(select(Traveler)).all() == []


@pytest.mark.parametrize("field", ["name", "email", "password"])
def test_required_fields(api, field):
    client, engine = api
    payload = registration()
    del payload[field]
    response = client.post("/auth/register", json=payload)

    assert response.status_code == 422
    assert "Travel-pass-123" not in response.text
    with Session(engine) as session:
        assert session.exec(select(Traveler)).all() == []


def test_exactly_72_utf8_bytes_are_accepted_and_hashes_use_unique_salts(api):
    client, engine = api
    password = "é" * 36
    for email in ["one@example.com", "two@example.com"]:
        assert client.post("/auth/register", json=registration(email=email, password=password)).status_code == 201

    with Session(engine) as session:
        travelers = session.exec(select(Traveler)).all()
        assert len(travelers) == 2
        assert travelers[0].password_hash != travelers[1].password_hash
        assert all(bcrypt.checkpw(password.encode(), traveler.password_hash.encode()) for traveler in travelers)


def test_database_url_environment_setting(tmp_path, monkeypatch):
    database_path = tmp_path / "configured.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    app = create_app()
    with TestClient(app) as client:
        assert client.post("/auth/register", json=registration()).status_code == 201
    assert database_path.exists()
