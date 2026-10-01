import os
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import create_engine


DEFAULT_DATABASE_URL = f"sqlite:///{(Path(__file__).resolve().parents[1] / 'taasheera.db').as_posix()}"


def build_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # FastAPI may use different threads during a request. Sessions stay per-request.
    connect_args = {"check_same_thread": False} if make_url(url).get_backend_name() == "sqlite" else {}
    return create_engine(url, connect_args=connect_args)
