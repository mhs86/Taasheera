"""Add a separate, traveler-owned profile table."""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "d37a5b1e9c42"
down_revision = "c82a91f4d670"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "travelerprofile",
        sa.Column("traveler_id", sa.Integer(), nullable=False),
        sa.Column("surname", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("given_names", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("nationality", sqlmodel.sql.sqltypes.AutoString(length=3), nullable=True),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("address_line1", sa.Text(), nullable=True),
        sa.Column("address_line2", sa.Text(), nullable=True),
        sa.Column("address_city", sa.Text(), nullable=True),
        sa.Column("address_region", sa.Text(), nullable=True),
        sa.Column("address_postal_code", sa.Text(), nullable=True),
        sa.Column("address_country", sqlmodel.sql.sqltypes.AutoString(length=3), nullable=True),
        sa.ForeignKeyConstraint(["traveler_id"], ["traveler.id"]),
        sa.PrimaryKeyConstraint("traveler_id"),
    )


def downgrade():
    op.drop_table("travelerprofile")
