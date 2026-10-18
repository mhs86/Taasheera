"""Store the verified Google email separately from the traveler's contact email."""
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "b14c9f30e2a7"
down_revision = "aeccbbace2e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("traveler", sa.Column("sso_email", sqlmodel.sql.sqltypes.AutoString(length=254), nullable=True))
    op.create_index("ix_traveler_sso_email", "traveler", ["sso_email"], unique=False)
    # Legacy Google identities were created only after verified-email sign-in.
    # Their original email is the only historical provider email we retained.
    op.execute(sa.text("UPDATE traveler SET sso_email = email WHERE id IN (SELECT traveler_id FROM googleidentity)"))


def downgrade():
    with op.batch_alter_table("traveler") as batch:
        batch.drop_index("ix_traveler_sso_email")
        batch.drop_column("sso_email")
