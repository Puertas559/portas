"""add sales execution

Revision ID: 5c8d21a09f42
Revises: 4f9a7c2de611
"""
from alembic import op
import sqlalchemy as sa

revision = "5c8d21a09f42"
down_revision = "4f9a7c2de611"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.add_column(sa.Column("owner_name", sa.String(length=160), nullable=False, server_default="Equipo comercial"))
        batch_op.add_column(sa.Column("estimated_value", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("probability", sa.Integer(), nullable=False, server_default="20"))
        batch_op.create_index(batch_op.f("ix_opportunities_owner_name"), ["owner_name"], unique=False)
    op.create_table("sales_tasks",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False), sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sequence_step", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)), sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"))
    for name, columns in (("ix_sales_tasks_opportunity_id", ["opportunity_id"]), ("ix_sales_tasks_due_at", ["due_at"]), ("ix_sales_tasks_status", ["status"]), ("ix_sales_tasks_channel", ["channel"])):
        op.create_index(name, "sales_tasks", columns)
    op.create_table("visit_records",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=False), sa.Column("measurements", sa.Text()),
        sa.Column("needs", sa.Text()), sa.Column("notes", sa.Text()), sa.Column("next_step", sa.Text()),
        sa.Column("photos", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"))
    op.create_index("ix_visit_records_opportunity_id", "visit_records", ["opportunity_id"])
    op.create_index("ix_visit_records_visited_at", "visit_records", ["visited_at"])
    op.create_table("proposals",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=60), nullable=False, unique=True), sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False), sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False), sa.Column("pdf_filename", sa.String(length=300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"))
    for name, columns in (("ix_proposals_opportunity_id", ["opportunity_id"]), ("ix_proposals_number", ["number"]), ("ix_proposals_status", ["status"]), ("ix_proposals_created_at", ["created_at"])):
        op.create_index(name, "proposals", columns, unique=name == "ix_proposals_number")


def downgrade():
    op.drop_table("proposals")
    op.drop_table("visit_records")
    op.drop_table("sales_tasks")
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_index(batch_op.f("ix_opportunities_owner_name"))
        batch_op.drop_column("probability")
        batch_op.drop_column("estimated_value")
        batch_op.drop_column("owner_name")
