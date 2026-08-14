"""add automatic prospecting

Revision ID: 9b7e3d4a21c8
Revises: 28cff119878d
Create Date: 2026-08-14 14:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "9b7e3d4a21c8"
down_revision = "28cff119878d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collector_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sources_scanned", sa.Integer(), nullable=False),
        sa.Column("items_scanned", sa.Integer(), nullable=False),
        sa.Column("signals_created", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collector_runs_started_at", "collector_runs", ["started_at"])
    op.create_index("ix_collector_runs_status", "collector_runs", ["status"])
    op.create_table(
        "prospect_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=220), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_reliability", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("department", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("products", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prospect_signals_fingerprint", "prospect_signals", ["fingerprint"], unique=True)
    op.create_index("ix_prospect_signals_company_name", "prospect_signals", ["company_name"])
    op.create_index("ix_prospect_signals_source_name", "prospect_signals", ["source_name"])
    op.create_index("ix_prospect_signals_score", "prospect_signals", ["score"])
    op.create_index("ix_prospect_signals_level", "prospect_signals", ["level"])
    op.create_index("ix_prospect_signals_status", "prospect_signals", ["status"])
    op.create_index("ix_prospect_signals_opportunity_id", "prospect_signals", ["opportunity_id"])


def downgrade():
    op.drop_table("prospect_signals")
    op.drop_table("collector_runs")
