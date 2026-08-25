"""add autonomous HUB events

Revision ID: ed24b6c19f01
Revises: ab81dca7e924
"""
from alembic import op
import sqlalchemy as sa

revision = "ed24b6c19f01"
down_revision = "ab81dca7e924"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('hub_event_sources',
        sa.Column('id',sa.Integer(),primary_key=True), sa.Column('tenant_id',sa.Integer(),nullable=False),
        sa.Column('name',sa.String(220),nullable=False), sa.Column('url',sa.String(1200),nullable=False),
        sa.Column('country',sa.String(80)), sa.Column('source_type',sa.String(50),nullable=False,server_default='OFFICIAL'),
        sa.Column('priority',sa.String(10),nullable=False,server_default='B'), sa.Column('status',sa.String(30),nullable=False,server_default='ACTIVE'),
        sa.Column('last_checked_at',sa.DateTime(timezone=True)), sa.Column('last_error',sa.Text()), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'],['tenants.id'],ondelete='CASCADE'), sa.UniqueConstraint('tenant_id','url',name='uq_hub_source_url'))
    op.create_index('ix_hub_event_sources_tenant_id','hub_event_sources',['tenant_id']);op.create_index('ix_hub_event_sources_status','hub_event_sources',['status'])
    op.create_table('hub_events',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),nullable=False),sa.Column('source_id',sa.Integer()),
        sa.Column('name',sa.String(320),nullable=False),sa.Column('normalized_key',sa.String(500),nullable=False),sa.Column('start_date',sa.Date()),sa.Column('end_date',sa.Date()),
        sa.Column('city',sa.String(160)),sa.Column('country',sa.String(80),nullable=False,server_default='Paraguay'),sa.Column('organizer',sa.String(260)),sa.Column('url',sa.String(1200)),sa.Column('event_type',sa.String(80)),
        sa.Column('sectors',sa.JSON(),nullable=False),sa.Column('description',sa.Text()),sa.Column('source_mode',sa.String(30),nullable=False,server_default='MANUAL'),sa.Column('status',sa.String(30),nullable=False,server_default='DETECTED'),
        sa.Column('confidence',sa.Integer(),nullable=False,server_default='50'),sa.Column('commercial_score',sa.Integer(),nullable=False,server_default='0'),sa.Column('economic_score',sa.Integer(),nullable=False,server_default='0'),sa.Column('strategic_score',sa.Integer(),nullable=False,server_default='0'),sa.Column('total_score',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('score_details',sa.JSON(),nullable=False),sa.Column('cost_estimate',sa.Numeric(18,2),nullable=False,server_default='0'),sa.Column('currency',sa.String(3),nullable=False,server_default='USD'),sa.Column('participation_mode',sa.String(40)),sa.Column('projection',sa.JSON(),nullable=False),sa.Column('actual_results',sa.JSON(),nullable=False),sa.Column('notes',sa.Text()),sa.Column('approved_at',sa.DateTime(timezone=True)),sa.Column('closed_at',sa.DateTime(timezone=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'],['tenants.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['source_id'],['hub_event_sources.id'],ondelete='SET NULL'),sa.UniqueConstraint('tenant_id','normalized_key',name='uq_hub_event_key'))
    for col in ['tenant_id','source_id','name','normalized_key','source_mode','status','total_score','created_at']:op.create_index(f'ix_hub_events_{col}','hub_events',[col])
    op.create_table('hub_event_accounts',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),nullable=False),sa.Column('event_id',sa.Integer(),nullable=False),sa.Column('company_id',sa.Integer()),sa.Column('company_name',sa.String(280),nullable=False),sa.Column('website',sa.String(1200)),sa.Column('role',sa.String(80),nullable=False,server_default='PARTICIPANT'),sa.Column('tier',sa.String(10),nullable=False,server_default='C'),sa.Column('icp_score',sa.Integer(),nullable=False,server_default='0'),sa.Column('contact_name',sa.String(220)),sa.Column('contact_role',sa.String(180)),sa.Column('email',sa.String(320)),sa.Column('whatsapp',sa.String(120)),sa.Column('hypothesis',sa.Text()),sa.Column('conversation_result',sa.String(80)),sa.Column('next_action',sa.String(400)),sa.Column('next_action_at',sa.DateTime(timezone=True)),sa.Column('status',sa.String(30),nullable=False,server_default='MAPPED'),sa.Column('sent_to_radar_at',sa.DateTime(timezone=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'],['tenants.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['event_id'],['hub_events.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['company_id'],['companies.id'],ondelete='SET NULL'))
    for col in ['tenant_id','event_id','company_id','company_name','tier','status']:op.create_index(f'ix_hub_event_accounts_{col}','hub_event_accounts',[col])
    op.create_table('hub_event_actions',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),nullable=False),sa.Column('event_id',sa.Integer(),nullable=False),sa.Column('phase',sa.String(20),nullable=False),sa.Column('title',sa.String(400),nullable=False),sa.Column('due_at',sa.DateTime(timezone=True)),sa.Column('owner_name',sa.String(180),nullable=False,server_default='Equipe HUB'),sa.Column('status',sa.String(30),nullable=False,server_default='PENDING'),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.ForeignKeyConstraint(['tenant_id'],['tenants.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['event_id'],['hub_events.id'],ondelete='CASCADE'))
    for col in ['tenant_id','event_id','phase','due_at','status']:op.create_index(f'ix_hub_event_actions_{col}','hub_event_actions',[col])


def downgrade():
    op.drop_table('hub_event_actions');op.drop_table('hub_event_accounts');op.drop_table('hub_events');op.drop_table('hub_event_sources')
