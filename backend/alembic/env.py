"""Alembic uses the same database URL and SQLModel metadata as the app."""

import os

from alembic import context
from sqlmodel import SQLModel

from app import models  # noqa: F401 - register table models in metadata
from app.database import DEFAULT_DATABASE_URL, build_engine


config = context.config
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        connections = [supplied_connection]
        engine = None
    else:
        engine = build_engine()
        connections = [engine.connect()]
    try:
        for connection in connections:
            context.configure(connection=connection, target_metadata=target_metadata,
                              render_as_batch=True, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        if engine is not None:
            connections[0].close()
            engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
