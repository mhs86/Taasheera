"""Keep assistant chat history per traveler and application (US 111)."""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "c4a8d2f61b93"
down_revision = "e9776504c5f8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assistantmessage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("traveler_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"]),
        sa.ForeignKeyConstraint(["traveler_id"], ["traveler.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assistantmessage") as batch:
        batch.create_index(batch.f("ix_assistantmessage_traveler_id"), ["traveler_id"], unique=False)
        batch.create_index(batch.f("ix_assistantmessage_application_id"), ["application_id"], unique=False)


def downgrade():
    with op.batch_alter_table("assistantmessage") as batch:
        batch.drop_index(batch.f("ix_assistantmessage_application_id"))
        batch.drop_index(batch.f("ix_assistantmessage_traveler_id"))
    op.drop_table("assistantmessage")
