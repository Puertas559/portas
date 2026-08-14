"""add company contact fields

Revision ID: 4f9a7c2de611
Revises: e4b80d9c71fa
"""
from alembic import op
import sqlalchemy as sa

revision = "4f9a7c2de611"
down_revision = "e4b80d9c71fa"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("companies") as batch_op:
        batch_op.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("phone", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("whatsapp", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=240), nullable=True))
        batch_op.add_column(sa.Column("linkedin_url", sa.String(length=700), nullable=True))
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.add_column(sa.Column("contact_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_opportunities_next_action_at"), ["next_action_at"], unique=False)


def downgrade():
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_index(batch_op.f("ix_opportunities_next_action_at"))
        batch_op.drop_column("next_action_at")
        batch_op.drop_column("contact_verified")
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_column("linkedin_url")
        batch_op.drop_column("email")
        batch_op.drop_column("whatsapp")
        batch_op.drop_column("phone")
        batch_op.drop_column("address")
