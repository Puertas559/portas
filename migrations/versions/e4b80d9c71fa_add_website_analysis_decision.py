"""add website analysis decision and messages

Revision ID: e4b80d9c71fa
Revises: c31a8f705d12
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b80d9c71fa"
down_revision = "c31a8f705d12"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("website_analyses") as batch_op:
        batch_op.add_column(sa.Column("decision", sa.String(length=30), nullable=False, server_default="PENDING"))
        batch_op.add_column(sa.Column("opportunity_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("whatsapp_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_subject", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("email_body", sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f("ix_website_analyses_decision"), ["decision"], unique=False)
        batch_op.create_index(batch_op.f("ix_website_analyses_opportunity_id"), ["opportunity_id"], unique=False)
        batch_op.create_foreign_key("fk_website_analysis_opportunity", "opportunities", ["opportunity_id"], ["id"], ondelete="SET NULL")


def downgrade():
    with op.batch_alter_table("website_analyses") as batch_op:
        batch_op.drop_constraint("fk_website_analysis_opportunity", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_website_analyses_opportunity_id"))
        batch_op.drop_index(batch_op.f("ix_website_analyses_decision"))
        batch_op.drop_column("email_body")
        batch_op.drop_column("email_subject")
        batch_op.drop_column("whatsapp_message")
        batch_op.drop_column("opportunity_id")
        batch_op.drop_column("decision")
