"""Add visa applications and their answers for the guided questionnaire."""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "1f04330ae8cb"
down_revision = "e6f81a73c902"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("traveler_id", sa.Integer(), nullable=False),
        sa.Column("questionnaire_id", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("questionnaire_version", sa.Integer(), nullable=False),
        sa.Column("destination", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("visa_type", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["traveler_id"], ["traveler.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("application") as batch:
        batch.create_index(batch.f("ix_application_traveler_id"), ["traveler_id"], unique=False)
    op.create_table(
        "applicationanswer",
        sa.Column("application_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("question_id", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("answered_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"]),
        sa.PrimaryKeyConstraint("application_id", "question_id"),
    )


def downgrade():
    op.drop_table("applicationanswer")
    with op.batch_alter_table("application") as batch:
        batch.drop_index(batch.f("ix_application_traveler_id"))
    op.drop_table("application")
