"""Upgrade a fresh database or adopt an exact pre-Alembic local schema."""

import argparse

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlmodel import SQLModel

from app import models  # noqa: F401 - register SQLModel tables
from app.database import build_engine
from app.schema import migration_config, schema_revision


def upgrade() -> None:
    engine = build_engine()
    config = migration_config()
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
            current = MigrationContext.configure(connection).get_current_revision()
            if current is None and tables:
                # Local databases created by the old create_all startup have no
                # revision marker. Stamp only when they match the committed model.
                differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
                if differences:
                    # Admit only complete known historical create_all schemas.
                    signatures = set()
                    for difference in differences:
                        kind = difference[0] if isinstance(difference, tuple) else None
                        if kind == "add_column":
                            signatures.add((kind, difference[2], difference[3].name))
                        elif kind == "add_index":
                            signatures.add((kind, difference[1].name))
                        elif kind == "add_table":
                            signatures.add((kind, difference[1].name))
                        else:
                            raise RuntimeError("Existing unversioned schema differs from a known migration.")
                    otp = {
                        ("add_column", "traveler", "auth_type"),
                        ("add_column", "traveler", "last_login_method"),
                        ("add_column", "traveler", "last_login_at"),
                        ("add_index", "ix_traveler_auth_type"),
                        ("add_table", "passwordresetchallenge"),
                        ("add_index", "ix_passwordresetchallenge_expires_at"),
                    }
                    sso = {("add_column", "traveler", "sso_email"),
                           ("add_index", "ix_traveler_sso_email")}
                    profile = {("add_table", "travelerprofile")}
                    session_details = {
                        ("add_column", "authsession", "device_label"),
                        ("add_column", "authsession", "created_at"),
                        ("add_column", "authsession", "last_active_at"),
                    }
                    if len(signatures) != len(differences) or signatures not in (
                        session_details, profile | session_details,
                        otp | profile | session_details, otp | sso | profile | session_details,
                    ):
                        raise RuntimeError("Existing unversioned schema differs from a known migration. Back it up before repair.")
                    prior_revision = (
                        "d37a5b1e9c42" if signatures == session_details else
                        "c82a91f4d670" if signatures == profile | session_details else
                        "b14c9f30e2a7" if signatures == otp | profile | session_details else
                        "aeccbbace2e6"
                    )
                    command.stamp(config, prior_revision)
                    command.upgrade(config, "head")
                else:
                    command.stamp(config, "head")
                    if "admin_user_auth" not in inspect(connection).get_view_names():
                        from app.admin_reporting import ADMIN_USER_VIEW
                        connection.execute(text(ADMIN_USER_VIEW))
                print("Adopted existing schema at the current revision.")
            else:
                command.upgrade(config, "head")
                print("Database migrations are current.")
    finally:
        engine.dispose()


def status() -> None:
    engine = build_engine()
    try:
        current, head = schema_revision(engine)
        print(f"Current: {current or 'none'}; head: {head}")
        if current != head:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("upgrade", "status"))
    choice = parser.parse_args().command
    if choice == "upgrade":
        upgrade()
    else:
        status()
