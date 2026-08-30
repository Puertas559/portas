"""radar v2 intelligence

Revision ID: b82d4e91c5af
Revises: 7a91f3c2d640
"""
from alembic import op
import sqlalchemy as sa

revision = "b82d4e91c5af"
down_revision = "7a91f3c2d640"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("company_size", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("employee_estimate", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("facility_profile", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("account_fit_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("accessibility_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("momentum_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("watch_status", sa.String(length=30), nullable=False, server_default="WATCH"))
        batch.add_column(sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_companies_watch_status", ["watch_status"])
        batch.create_index("ix_companies_last_signal_at", ["last_signal_at"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("role", sa.String(length=180)),
        sa.Column("buying_role", sa.String(length=40), nullable=False, server_default="UNKNOWN"),
        sa.Column("influence_score", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("email", sa.String(length=320)), sa.Column("phone", sa.String(length=120)),
        sa.Column("whatsapp", sa.String(length=120)), sa.Column("linkedin_url", sa.String(length=700)),
        sa.Column("source_url", sa.String(length=1200)), sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("verified_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(length=30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("influence_score BETWEEN 0 AND 100", name="ck_contact_influence"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_contact_confidence"),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])
    op.create_index("ix_contacts_buying_role", "contacts", ["buying_role"])
    op.create_index("ix_contacts_status", "contacts", ["status"])

    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"), sa.Column("reason", sa.Text()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ACTIVE"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)), sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "company_id", name="uq_watchlist_company"),
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_watchlist_priority"),
    )
    op.create_index("ix_watchlists_tenant_id", "watchlists", ["tenant_id"])
    op.create_index("ix_watchlists_company_id", "watchlists", ["company_id"])
    op.create_index("ix_watchlists_status", "watchlists", ["status"])
    op.create_index("ix_watchlists_next_check_at", "watchlists", ["next_check_at"])

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("lifecycle_stage", sa.String(length=50), nullable=False, server_default="DISCOVERED"))
        batch.add_column(sa.Column("buying_window_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("demand_probability", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("momentum_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("estimated_deal_min", sa.Numeric(18,2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("estimated_deal_max", sa.Numeric(18,2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("stage_confidence", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_projects_lifecycle_stage", ["lifecycle_stage"])

    with op.batch_alter_table("opportunities") as batch:
        batch.add_column(sa.Column("lifecycle_stage", sa.String(length=50), nullable=False, server_default="SALES_READY"))
        batch.add_column(sa.Column("buying_window_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("accessibility_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("momentum_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("why_now", sa.Text()))
        batch.add_column(sa.Column("next_best_action", sa.Text()))
        batch.add_column(sa.Column("deal_value_min", sa.Numeric(18,2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("deal_value_max", sa.Numeric(18,2), nullable=False, server_default="0"))
        batch.create_index("ix_opportunities_lifecycle_stage", ["lifecycle_stage"])

    with op.batch_alter_table("signals") as batch:
        batch.add_column(sa.Column("impact_score", sa.Integer(), nullable=False, server_default="50"))
        batch.add_column(sa.Column("buying_window_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lifecycle_stage", sa.String(length=50), nullable=False, server_default="DISCOVERED"))
        batch.add_column(sa.Column("causality", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("product_hypothesis", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.create_index("ix_signals_lifecycle_stage", ["lifecycle_stage"])

    with op.batch_alter_table("prospect_signals") as batch:
        batch.add_column(sa.Column("buying_window_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lifecycle_stage", sa.String(length=50), nullable=False, server_default="DISCOVERED"))
        batch.add_column(sa.Column("momentum_delta", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("demand_probability", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("causality", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("estimated_deal_min", sa.Numeric(18,2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("estimated_deal_max", sa.Numeric(18,2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("why_now", sa.Text()))
        batch.create_index("ix_prospect_signals_lifecycle_stage", ["lifecycle_stage"])


def downgrade():
    with op.batch_alter_table("prospect_signals") as batch:
        batch.drop_index("ix_prospect_signals_lifecycle_stage")
        for col in ["why_now","estimated_deal_max","estimated_deal_min","causality","demand_probability","momentum_delta","lifecycle_stage","buying_window_score"]:
            batch.drop_column(col)
    with op.batch_alter_table("signals") as batch:
        batch.drop_index("ix_signals_lifecycle_stage")
        for col in ["product_hypothesis","causality","lifecycle_stage","buying_window_score","impact_score"]:
            batch.drop_column(col)
    with op.batch_alter_table("opportunities") as batch:
        batch.drop_index("ix_opportunities_lifecycle_stage")
        for col in ["deal_value_max","deal_value_min","next_best_action","why_now","confidence_score","momentum_score","accessibility_score","buying_window_score","lifecycle_stage"]:
            batch.drop_column(col)
    with op.batch_alter_table("projects") as batch:
        batch.drop_index("ix_projects_lifecycle_stage")
        for col in ["stage_confidence","estimated_deal_max","estimated_deal_min","momentum_score","demand_probability","buying_window_score","lifecycle_stage"]:
            batch.drop_column(col)
    op.drop_table("watchlists")
    op.drop_table("contacts")
    with op.batch_alter_table("companies") as batch:
        batch.drop_index("ix_companies_last_signal_at")
        batch.drop_index("ix_companies_watch_status")
        for col in ["last_signal_at","watch_status","momentum_score","accessibility_score","account_fit_score","facility_profile","employee_estimate","company_size"]:
            batch.drop_column(col)
