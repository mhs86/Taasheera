"""add traveler role and status

Revision ID: 1a1ce7fbb089
Revises: aeccbbace2e6
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1a1ce7fbb089'
down_revision: Union[str, Sequence[str], None] = 'aeccbbace2e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Existing accounts become active travelers through the server defaults."""
    # Handwritten: autogenerate does not emit CHECK constraints.
    with op.batch_alter_table('traveler', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=20), server_default='traveler', nullable=False))
        batch_op.add_column(sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), server_default='active', nullable=False))
        batch_op.create_check_constraint('ck_traveler_role', "role IN ('traveler', 'support', 'admin')")
        batch_op.create_check_constraint('ck_traveler_status', "status IN ('active', 'suspended')")


def downgrade() -> None:
    """Drops only access settings, never traveler data; role assignments must be redone after re-upgrading."""
    with op.batch_alter_table('traveler', schema=None) as batch_op:
        batch_op.drop_constraint('ck_traveler_status', type_='check')
        batch_op.drop_constraint('ck_traveler_role', type_='check')
        batch_op.drop_column('status')
        batch_op.drop_column('role')
