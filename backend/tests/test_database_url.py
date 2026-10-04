from app.database import normalize_database_url


def test_managed_postgres_url_uses_installed_psycopg_driver():
    assert normalize_database_url("postgresql://user:secret@db.example/test") == (
        "postgresql+psycopg://user:secret@db.example/test"
    )
    assert normalize_database_url("postgresql+psycopg://user@db.example/test") == (
        "postgresql+psycopg://user@db.example/test"
    )
    assert normalize_database_url("sqlite:///local.db") == "sqlite:///local.db"
