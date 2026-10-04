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
                    raise RuntimeError(
                        "Existing unversioned schema differs from the initial migration. "
                        "Back it up, update it to the current local schema, then retry."
                    )
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
