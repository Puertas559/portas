"""site diagnostics and digital presence

Revision ID: ab81dca7e924
Revises: f7c2a11b9e30
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

revision = "ab81dca7e924"
down_revision = "f7c2a11b9e30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("companies", sa.Column("digital_presence", sa.JSON(), nullable=True))
    op.add_column("website_analyses", sa.Column("alternative_sites", sa.JSON(), nullable=True))
    op.add_column("website_analyses", sa.Column("diagnostics", sa.JSON(), nullable=True))
    op.execute("UPDATE companies SET digital_presence = '{}' WHERE digital_presence IS NULL")
    op.execute("UPDATE website_analyses SET alternative_sites = '[]' WHERE alternative_sites IS NULL")
    op.execute("UPDATE website_analyses SET diagnostics = '{}' WHERE diagnostics IS NULL")


def downgrade():
    op.drop_column("website_analyses", "diagnostics")
    op.drop_column("website_analyses", "alternative_sites")
    op.drop_column("companies", "digital_presence")
