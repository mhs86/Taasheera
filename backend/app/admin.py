"""Read-only account reporting for trusted operators: python -m app.admin."""
import argparse
import json

from sqlalchemy import text

from .database import build_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--summary', action='store_true')
    options = parser.parse_args()
    if not 1 <= options.limit <= 1000:
        parser.error('--limit must be between 1 and 1000')
    engine = build_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text('PRAGMA query_only = ON' if engine.dialect.name == 'sqlite' else 'SET TRANSACTION READ ONLY'))
            query = ('SELECT auth_type, password_enabled, google_enabled, COUNT(*) AS users '
                     'FROM admin_user_auth GROUP BY auth_type,password_enabled,google_enabled '
                     'ORDER BY auth_type,password_enabled,google_enabled' if options.summary else
                     'SELECT * FROM admin_user_auth ORDER BY id DESC LIMIT :limit')
            rows = connection.execute(text(query), {'limit': options.limit}).mappings().all()
            print(json.dumps([dict(row) for row in rows], indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
