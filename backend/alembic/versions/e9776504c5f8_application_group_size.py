"""Record how many people travel together on an application (US 4)."""

from alembic import op
import sqlalchemy as sa


revision = "e9776504c5f8"
down_revision = "1f04330ae8cb"
branch_labels = None
depends_on = None


def upgrade():
    # Existing applications were all started by one traveler.
    with op.batch_alter_table("application") as batch:
        batch.add_column(sa.Column("group_size", sa.Integer(), server_default="1", nullable=False))


def downgrade():
    with op.batch_alter_table("application") as batch:
        batch.drop_column("group_size")
