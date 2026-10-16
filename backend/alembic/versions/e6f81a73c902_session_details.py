"""Record session device and activity timestamps without guessing for old rows."""
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "e6f81a73c902"
down_revision = "d37a5b1e9c42"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("authsession") as batch:
        batch.add_column(sa.Column("device_label", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("authsession") as batch:
        batch.drop_column("last_active_at")
        batch.drop_column("created_at")
        batch.drop_column("device_label")
