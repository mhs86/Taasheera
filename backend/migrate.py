"""Upgrade a fresh database or adopt an exact pre-Alembic local schema."""

import argparse

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
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
                    # The known pre-SSO baseline can be adopted and upgraded.
                    # Any unrelated drift still prevents stamping or data changes.
                    expected_column = any(d[0] == "add_column" and d[2] == "traveler"
                                          and d[3].name == "sso_email" for d in differences)
                    expected_index = any(d[0] == "add_index" and d[1].name == "ix_traveler_sso_email"
                                         for d in differences)
                    if len(differences) != 2 or not expected_column or not expected_index:
                        raise RuntimeError(
                            "Existing unversioned schema differs from the initial migration. "
                            "Back it up, update it to the current local schema, then retry."
                        )
                    command.stamp(config, "aeccbbace2e6")
                    command.upgrade(config, "head")
                else:
                    command.stamp(config, "head")
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
