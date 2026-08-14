"""add website qualification

Revision ID: c31a8f705d12
Revises: 9b7e3d4a21c8
"""
from alembic import op
import sqlalchemy as sa

revision = "c31a8f705d12"
down_revision = "9b7e3d4a21c8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "website_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1200), nullable=False),
        sa.Column("company_name", sa.String(length=240), nullable=False),
        sa.Column("sector", sa.String(length=160), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phones", sa.JSON(), nullable=False),
        sa.Column("whatsapp", sa.String(length=120), nullable=True),
        sa.Column("emails", sa.JSON(), nullable=False),
        sa.Column("contacts", sa.JSON(), nullable=False),
        sa.Column("social_links", sa.JSON(), nullable=False),
        sa.Column("company_size", sa.String(length=80), nullable=False),
        sa.Column("potential_score", sa.Integer(), nullable=False),
        sa.Column("potential_level", sa.String(length=30), nullable=False),
        sa.Column("products", sa.JSON(), nullable=False),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("pages_analyzed", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_website_analyses_created_at"), "website_analyses", ["created_at"], unique=False)
    op.create_index(op.f("ix_website_analyses_potential_level"), "website_analyses", ["potential_level"], unique=False)
    op.create_index(op.f("ix_website_analyses_potential_score"), "website_analyses", ["potential_score"], unique=False)
    op.create_index(op.f("ix_website_analyses_status"), "website_analyses", ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_website_analyses_status"), table_name="website_analyses")
    op.drop_index(op.f("ix_website_analyses_potential_score"), table_name="website_analyses")
    op.drop_index(op.f("ix_website_analyses_potential_level"), table_name="website_analyses")
    op.drop_index(op.f("ix_website_analyses_created_at"), table_name="website_analyses")
    op.drop_table("website_analyses")
