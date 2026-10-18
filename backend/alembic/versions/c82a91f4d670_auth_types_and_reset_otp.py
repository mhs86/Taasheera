"""Classify accounts, add one-time email challenges and private admin reporting."""
from alembic import op
import sqlalchemy as sa
import sqlmodel

from app.admin_reporting import ADMIN_USER_VIEW

revision = "c82a91f4d670"
down_revision = "b14c9f30e2a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("traveler", sa.Column("auth_type", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True))
    op.add_column("traveler", sa.Column("last_login_method", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True))
    op.add_column("traveler", sa.Column("last_login_at", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE traveler SET auth_type = CASE WHEN password_hash = '' THEN 'google' ELSE 'email_password' END"))
    with op.batch_alter_table("traveler") as batch:
        batch.alter_column("auth_type", existing_type=sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False)
        batch.create_check_constraint("ck_traveler_auth_type", "(auth_type = 'google' AND password_hash = '') OR (auth_type = 'email_password' AND password_hash <> '')")
        batch.create_index("ix_traveler_auth_type", ["auth_type"], unique=False)
    op.create_table("passwordresetchallenge",
        sa.Column("traveler_id", sa.Integer(), nullable=False),
        sa.Column("nonce", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("code_digest", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["traveler_id"], ["traveler.id"]),
        sa.PrimaryKeyConstraint("traveler_id"),
    )
    op.create_index("ix_passwordresetchallenge_expires_at", "passwordresetchallenge", ["expires_at"], unique=False)
    # Prior emailed links cannot bypass the newly required OTP verification.
    op.execute(sa.text("UPDATE passwordresettoken SET used = true"))
    op.execute(sa.text(ADMIN_USER_VIEW))


def downgrade():
    op.execute(sa.text("DROP VIEW admin_user_auth"))
    op.drop_index("ix_passwordresetchallenge_expires_at", table_name="passwordresetchallenge")
    op.drop_table("passwordresetchallenge")
    with op.batch_alter_table("traveler") as batch:
        batch.drop_constraint("ck_traveler_auth_type", type_="check")
        batch.drop_index("ix_traveler_auth_type")
        batch.drop_column("last_login_at")
        batch.drop_column("last_login_method")
        batch.drop_column("auth_type")
