"""Upgrade a database; adopt an unversioned local schema only when it exactly matches the current models or the initial revision."""

import argparse

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import CheckConstraint, MetaData, create_engine, inspect
from sqlmodel import SQLModel

from app import models  # noqa: F401 - register SQLModel tables
from app.database import build_engine
from app.schema import migration_config, schema_revision


BASELINE_REVISION = "aeccbbace2e6"  # Sprint 1 local databases were made by create_all from these models.


def revision_schema(revision: str) -> MetaData:
    """The schema a revision produces, rebuilt in a throwaway in-memory SQLite database."""
    scratch = create_engine("sqlite://")
    try:
        with scratch.begin() as connection:
            config = migration_config()  # A new Config: never the target database's.
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
            schema = MetaData()
            schema.reflect(connection)
    finally:
        scratch.dispose()
    schema.remove(schema.tables["alembic_version"])
    return schema


def differs(connection, metadata: MetaData) -> bool:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    if compare_metadata(context, metadata):
        return True
    # compare_metadata ignores CHECK constraints, and the role/status checks are the real guard.
    inspector = inspect(connection)
    return any(
        {check["name"] for check in inspector.get_check_constraints(table.name)}
        != {constraint.name for constraint in table.constraints if isinstance(constraint, CheckConstraint)}
        for table in metadata.tables.values()
    )


def upgrade() -> None:
    engine = build_engine()
    config = migration_config()
    try:
        with engine.begin() as connection:
            sqlite = connection.dialect.name == "sqlite"
            if sqlite:
                # pysqlite only opens a transaction before DML; open it now so an interrupted
                # table rebuild (CREATE _alembic_tmp_..., DROP, RENAME) rolls back as well.
                connection.exec_driver_sql("BEGIN")
            config.attributes["connection"] = connection
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
            current = MigrationContext.configure(connection).get_current_revision()
            if current is None and tables:
                # Local databases created by the old create_all startup have no
                # revision marker. Adopt them only when they match exactly.
                if not differs(connection, SQLModel.metadata):
                    command.stamp(config, "head")
                    print("Adopted existing schema at the current revision.")
                elif sqlite and not differs(connection, revision_schema(BASELINE_REVISION)):
                    command.stamp(config, BASELINE_REVISION)
                    command.upgrade(config, "head")
                    print("Adopted existing Sprint 1 schema at the initial revision and applied newer migrations.")
                else:
                    raise RuntimeError(
                        "Existing unversioned schema differs from the current models"
                        + (" and from the Sprint 1 schema" if sqlite else "")
                        + ". Back it up, then bring it to the current models or, if it is a disposable "
                        "local database, delete it and run again."
                    )
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
