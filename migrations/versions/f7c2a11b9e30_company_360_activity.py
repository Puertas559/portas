"""company 360 and activity log

Revision ID: f7c2a11b9e30
Revises: d91f0b2c7a44
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'f7c2a11b9e30'
down_revision = 'd91f0b2c7a44'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('companies') as batch:
        batch.add_column(sa.Column('legal_name', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('ruc', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('founded_year', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('headquarters', sa.String(length=260), nullable=True))
        batch.add_column(sa.Column('owners', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column('operation_plants', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column('key_activities', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column('commercial_notes', sa.Text(), nullable=True))
        batch.add_column(sa.Column('data_sources', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.create_index('ix_companies_ruc', ['ruc'], unique=False)

    op.create_table(
        'company_activities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('opportunity_id', sa.Integer(), sa.ForeignKey('opportunities.id', ondelete='SET NULL'), nullable=True),
        sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('activity_type', sa.String(length=50), nullable=False),
        sa.Column('channel', sa.String(length=40), nullable=True),
        sa.Column('direction', sa.String(length=20), nullable=False, server_default='OUTBOUND'),
        sa.Column('subject', sa.String(length=400), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('outcome', sa.String(length=80), nullable=True),
        sa.Column('next_action', sa.String(length=400), nullable=True),
        sa.Column('next_action_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=180), nullable=False, server_default='Equipo comercial'),
        sa.Column('extra_data', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    for col in ('tenant_id','company_id','opportunity_id','contact_id','activity_type','channel','outcome','next_action_at','occurred_at'):
        op.create_index(f'ix_company_activities_{col}', 'company_activities', [col], unique=False)


def downgrade():
    op.drop_table('company_activities')
    with op.batch_alter_table('companies') as batch:
        batch.drop_index('ix_companies_ruc')
        for col in ('data_sources','commercial_notes','key_activities','operation_plants','owners','headquarters','founded_year','ruc','legal_name'):
            batch.drop_column(col)
