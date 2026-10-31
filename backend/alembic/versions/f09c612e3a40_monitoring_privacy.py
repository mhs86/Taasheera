"""Applications, document access history and durable account erasure.

Revision ID: f09c612e3a40
Revises: b14ab372b1d2
"""
from alembic import op
import sqlalchemy as sa

revision = "f09c612e3a40"
down_revision = "b14ab372b1d2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("visaapplication",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("traveler_id", sa.Integer(), sa.ForeignKey("traveler.id"), nullable=False),
        sa.Column("destination", sa.String(3), nullable=False),
        sa.Column("nationality", sa.String(3), nullable=False),
        sa.Column("visa_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','IN_PROGRESS','READY','SUBMITTED','DECIDED','FAILED')",
                           name="ck_visaapplication_status"))
    op.create_index("ix_visaapplication_traveler_id", "visaapplication", ["traveler_id"])
    op.create_index("ix_visaapplication_status", "visaapplication", ["status"])
    op.create_table("documentaccess",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("traveler_id", sa.Integer(), sa.ForeignKey("traveler.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("traveler.id"), nullable=False),
        sa.Column("upload_id", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("traveler_id", "actor_id", "occurred_at"):
        op.create_index(f"ix_documentaccess_{column}", "documentaccess", [column])
    op.create_table("accounterasure",
        sa.Column("traveler_id", sa.Integer(), sa.ForeignKey("traveler.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ("accounterasure", "documentaccess", "visaapplication"):
        op.drop_table(table)
