from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

import migrate
from app.database import build_engine
from app.schema import migration_config


@pytest.mark.parametrize('unversioned', [False, True])
def test_sso_baseline_upgrades_accounts_and_admin_view_without_leaking_hashes(tmp_path, monkeypatch, unversioned):
    url = f'sqlite:///{tmp_path / "before-otp.db"}'
    monkeypatch.setenv('DATABASE_URL', url)
    command.upgrade(migration_config(), 'b14c9f30e2a7')
    engine = build_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO traveler(id,name,email,password_hash,sso_email) VALUES (1,'Password specimen','password@example.com','original-hash',NULL),(2,'Google specimen','google@example.com','','google@example.com'),(3,'Linked specimen','linked@example.com','linked-hash','linked-google@example.com')"))
        c.execute(text("INSERT INTO googleidentity(subject,traveler_id) VALUES ('google-sub',2),('linked-sub',3)"))
        c.execute(text("INSERT INTO passwordresettoken(token_hash,traveler_id,expires_at,used) VALUES ('old-link-hash',1,9999999999,false)"))
        if unversioned:
            c.execute(text('DROP TABLE alembic_version'))
    migrate.upgrade(); migrate.upgrade()
    with engine.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), SQLModel.metadata) == []
        rows = c.execute(text('SELECT * FROM admin_user_auth ORDER BY id')).mappings().all()
        assert [(r['auth_type'],r['password_enabled'],r['google_enabled']) for r in rows] == [('email_password',1,0),('google',0,1),('email_password',1,1)]
        assert all('password_hash' not in r and 'subject' not in r for r in rows)
        assert c.execute(text('SELECT password_hash FROM traveler WHERE id=1')).scalar_one() == 'original-hash'
        assert c.execute(text('SELECT used FROM passwordresettoken')).scalar_one()
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("UPDATE traveler SET auth_type='email_password' WHERE id=2"))
    engine.dispose()
