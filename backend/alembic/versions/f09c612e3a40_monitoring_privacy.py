"""Document access history and durable account erasure.

Revision ID: f09c612e3a40
Revises: e9776504c5f8
"""
from alembic import op
import sqlalchemy as sa

revision = "f09c612e3a40"
down_revision = "e9776504c5f8"
branch_labels = None
depends_on = None


def upgrade():
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
    for table in ("accounterasure", "documentaccess"):
        op.drop_table(table)
