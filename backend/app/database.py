import os
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import create_engine


DEFAULT_DATABASE_URL = f"sqlite:///{(Path(__file__).resolve().parents[1] / 'taasheera.db').as_posix()}"


def normalize_database_url(url: str) -> str:
    # Render and other managed Postgres hosts provide a generic SQLAlchemy URL.
    # Our pinned PostgreSQL driver is psycopg 3, not SQLAlchemy's psycopg2 default.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def build_engine(database_url: str | None = None):
    url = normalize_database_url(database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    # FastAPI may use different threads during a request. Sessions stay per-request.
    connect_args = {"check_same_thread": False} if make_url(url).get_backend_name() == "sqlite" else {}
    return create_engine(url, connect_args=connect_args)
