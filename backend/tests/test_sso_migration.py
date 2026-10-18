from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlmodel import Session, SQLModel

import migrate
from app.database import build_engine
from app.models import GoogleIdentity, Traveler
from app.schema import migration_config, schema_revision


def baseline(tmp_path, monkeypatch, *, unversioned=False):
    url = f"sqlite:///{tmp_path / 'baseline.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "aeccbbace2e6")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id,name,email,password_hash) VALUES (1,'Password owner','mhs86@mail.aub.edu','original-hash'),(2,'Google specimen','specimen@example.com','')"))
        connection.execute(text("INSERT INTO googleidentity(subject,traveler_id) VALUES ('legacy-google-subject',2)"))
        if unversioned:
            connection.execute(text("DROP TABLE alembic_version"))
    return engine


def test_migration_preserves_accounts_and_backfills_only_verified_google_records(tmp_path, monkeypatch):
    engine = baseline(tmp_path, monkeypatch)
    migrate.upgrade()
    migrate.upgrade()
    with Session(engine) as session:
        owner = session.get(Traveler, 1)
        google = session.get(Traveler, 2)
        assert owner.password_hash == "original-hash" and owner.sso_email is None
        assert google.sso_email == google.email == "specimen@example.com"
        assert session.get(GoogleIdentity, 'legacy-google-subject').traveler_id == 2
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
    assert schema_revision(engine)[0] == schema_revision(engine)[1]
    engine.dispose()


def test_known_unversioned_baseline_is_upgraded_without_erasing_users(tmp_path, monkeypatch):
    engine = baseline(tmp_path, monkeypatch, unversioned=True)
    migrate.upgrade()
    with Session(engine) as session:
        assert session.get(Traveler, 1).password_hash == "original-hash"
        assert session.get(Traveler, 2).sso_email == "specimen@example.com"
    engine.dispose()
