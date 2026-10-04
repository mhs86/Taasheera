"""Schema checks shared by API startup and the migration command."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def migration_config() -> Config:
    return Config(str(ALEMBIC_INI))


def schema_revision(engine) -> tuple[str | None, str]:
    config = migration_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current, head


def require_current_schema(engine) -> None:
    current, head = schema_revision(engine)
    if current != head:
        raise RuntimeError("Database schema is not current. Run 'python migrate.py upgrade' before starting the API.")
