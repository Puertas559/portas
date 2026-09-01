"""add technical survey v2 workflow

Revision ID: a6d2c4f89120
Revises: f3a9c4d27b11
"""
from alembic import op
import sqlalchemy as sa

revision = "a6d2c4f89120"
down_revision = "f3a9c4d27b11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "technical_surveys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("reference", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="DRAFT"),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("commercial", sa.JSON(), nullable=False),
        sa.Column("budget_total", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_notes", sa.Text(), nullable=True),
        sa.Column("signature_name", sa.String(length=220), nullable=True),
        sa.Column("signature_data", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_technical_survey_progress"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["validated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "reference", name="uq_technical_survey_reference"),
    )
    for column in ("tenant_id", "company_id", "opportunity_id", "reference", "status", "validated_by_user_id", "created_by_user_id", "updated_by_user_id", "created_at"):
        op.create_index(f"ix_technical_surveys_{column}", "technical_surveys", [column])

    op.create_table(
        "technical_survey_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("survey_id", sa.Integer(), nullable=False),
        sa.Column("group_key", sa.String(length=80), nullable=False),
        sa.Column("original_filename", sa.String(length=300), nullable=False),
        sa.Column("stored_filename", sa.String(length=300), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relative_path", sa.String(length=700), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["survey_id"], ["technical_surveys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "survey_id", "group_key", "created_by_user_id", "created_at"):
        op.create_index(f"ix_technical_survey_attachments_{column}", "technical_survey_attachments", [column])

    op.create_table(
        "technical_survey_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("survey_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["survey_id"], ["technical_surveys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "survey_id", "user_id", "action", "created_at"):
        op.create_index(f"ix_technical_survey_events_{column}", "technical_survey_events", [column])


def downgrade():
    op.drop_table("technical_survey_events")
    op.drop_table("technical_survey_attachments")
    op.drop_table("technical_surveys")
