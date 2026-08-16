"""sales workspace v5

Revision ID: d91f0b2c7a44
Revises: b82d4e91c5af
"""
from alembic import op
import sqlalchemy as sa

revision = "d91f0b2c7a44"
down_revision = "b82d4e91c5af"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("research_status", sa.String(length=30), nullable=False, server_default="PENDING"))
        batch.add_column(sa.Column("data_completeness_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_enriched_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_companies_research_status", ["research_status"], unique=False)
        batch.create_index("ix_companies_last_enriched_at", ["last_enriched_at"], unique=False)
    with op.batch_alter_table("opportunities") as batch:
        batch.add_column(sa.Column("lead_readiness_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("sales_ready", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("outcome_code", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("lost_reason", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("last_result_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_opportunities_lead_readiness_score", ["lead_readiness_score"], unique=False)
        batch.create_index("ix_opportunities_sales_ready", ["sales_ready"], unique=False)
        batch.create_index("ix_opportunities_outcome_code", ["outcome_code"], unique=False)
        batch.create_index("ix_opportunities_lost_reason", ["lost_reason"], unique=False)
        batch.create_index("ix_opportunities_last_result_at", ["last_result_at"], unique=False)
        batch.create_index("ix_opportunities_last_contact_at", ["last_contact_at"], unique=False)


def downgrade():
    with op.batch_alter_table("opportunities") as batch:
        for idx in ["ix_opportunities_last_contact_at","ix_opportunities_last_result_at","ix_opportunities_lost_reason","ix_opportunities_outcome_code","ix_opportunities_sales_ready","ix_opportunities_lead_readiness_score"]:
            batch.drop_index(idx)
        for col in ["last_contact_at","last_result_at","lost_reason","outcome_code","sales_ready","lead_readiness_score"]:
            batch.drop_column(col)
    with op.batch_alter_table("companies") as batch:
        batch.drop_index("ix_companies_last_enriched_at")
        batch.drop_index("ix_companies_research_status")
        batch.drop_column("last_enriched_at")
        batch.drop_column("data_completeness_score")
        batch.drop_column("research_status")
