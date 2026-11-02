"""Let travelers archive an application (US 79): a timestamp, null while it is active."""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "a7c3e91d5b20"
down_revision = "e9776504c5f8"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable with no default: every existing application stays active.
    with op.batch_alter_table("application") as batch:
        batch.add_column(sa.Column("archived_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("application") as batch:
        batch.drop_column("archived_at")
