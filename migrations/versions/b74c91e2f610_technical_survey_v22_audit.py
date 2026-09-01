"""technical survey v2.2 audit fixes

Revision ID: b74c91e2f610
Revises: a6d2c4f89120
"""
from alembic import op
import sqlalchemy as sa

revision = "b74c91e2f610"
down_revision = "a6d2c4f89120"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("technical_surveys") as batch_op:
        batch_op.add_column(sa.Column("quote_version", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("quote_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

def downgrade():
    with op.batch_alter_table("technical_surveys") as batch_op:
        batch_op.drop_column("quote_snapshot")
        batch_op.drop_column("quote_version")
