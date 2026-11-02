"""Retry queued deletions using explicit operator environment (no dotenv loading)."""
import os

from app.activity import activity_directory_from_environment
from app.config import AuthSettings
from app.database import build_engine
from app.passport.storage import PassportImageStorage
from app.privacy import retry_erasures
from app.schema import require_current_schema


def main():
    settings = AuthSettings.from_environment()
    directory = activity_directory_from_environment()
    storage_dir = os.environ.get("PASSPORT_STORAGE_DIR")
    if not storage_dir:
        raise SystemExit("Set PASSPORT_STORAGE_DIR explicitly before retrying account erasures.")
    engine = build_engine()
    try:
        require_current_schema(engine)
        pending = retry_erasures(engine, PassportImageStorage(storage_dir), directory, settings.jwt_secret)
    finally:
        engine.dispose()
    print(f"Pending erasures: {pending}")
    if pending:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
