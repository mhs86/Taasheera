"""Record when each account was created, backfilled from its registration event.

Revision ID: b14ab372b1d2
Revises: 1a1ce7fbb089
"""
from alembic import op
import sqlalchemy as sa

from app.admin_reporting import ADMIN_USER_VIEW


revision = "b14ab372b1d2"
down_revision = "1a1ce7fbb089"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("traveler", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    # Accounts registered before activity logging have no event and stay unknown (NULL).
    op.execute(sa.text(
        "UPDATE traveler SET created_at = (SELECT MIN(e.occurred_at) FROM activityevent e "
        "WHERE e.traveler_id = traveler.id AND e.event_type = 'registration')"
    ))


def downgrade():
    # SQLite rebuilds the traveler table to drop a column; the reporting view reads that table.
    op.execute(sa.text("DROP VIEW IF EXISTS admin_user_auth"))
    with op.batch_alter_table("traveler") as batch:
        batch.drop_column("created_at")
    op.execute(sa.text(ADMIN_USER_VIEW))
