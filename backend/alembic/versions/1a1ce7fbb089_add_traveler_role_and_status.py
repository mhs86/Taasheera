"""add traveler role and status

Revision ID: 1a1ce7fbb089
Revises: e6f81a73c902
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

from app.admin_reporting import ADMIN_USER_VIEW


# revision identifiers, used by Alembic.
revision: str = '1a1ce7fbb089'
down_revision: Union[str, Sequence[str], None] = 'e6f81a73c902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Existing accounts become active travelers through the server defaults."""
    # SQLite rebuilds the traveler table to add the CHECKs; the reporting view reads that table.
    op.execute(sa.text("DROP VIEW IF EXISTS admin_user_auth"))
    # Handwritten: autogenerate does not emit CHECK constraints.
    with op.batch_alter_table('traveler', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=20), server_default='traveler', nullable=False))
        batch_op.add_column(sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), server_default='active', nullable=False))
        batch_op.create_check_constraint('ck_traveler_role', "role IN ('traveler', 'support', 'admin')")
        batch_op.create_check_constraint('ck_traveler_status', "status IN ('active', 'suspended')")
    op.execute(sa.text(ADMIN_USER_VIEW))


def downgrade() -> None:
    """Drops only access settings, never traveler data; role assignments must be redone after re-upgrading."""
    op.execute(sa.text("DROP VIEW IF EXISTS admin_user_auth"))
    with op.batch_alter_table('traveler', schema=None) as batch_op:
        batch_op.drop_constraint('ck_traveler_status', type_='check')
        batch_op.drop_constraint('ck_traveler_role', type_='check')
        batch_op.drop_column('status')
        batch_op.drop_column('role')
    op.execute(sa.text(ADMIN_USER_VIEW))
