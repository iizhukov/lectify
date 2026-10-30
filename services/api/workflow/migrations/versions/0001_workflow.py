"""Owned workflow/node templates and immutable caller-owned snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0001_workflow'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workflow_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(128), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(4096), nullable=False),
        sa.Column('graph', sa.JSON, nullable=False),
        sa.Column('is_public', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.Integer, nullable=False),
        sa.Column('updated_at', sa.Integer, nullable=False))
    op.create_index('ix_workflow_templates_owner_id', 'workflow_templates', ['owner_id'])
    op.create_table('workflow_node_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(128), nullable=True),
        sa.Column('plugin_id', sa.String(128), nullable=False),
        sa.Column('plugin_version', sa.String(64), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(4096), nullable=False),
        sa.Column('parameters', sa.JSON, nullable=False),
        sa.Column('input_mapping', sa.JSON, nullable=False),
        sa.Column('prompt_id', sa.String(128), nullable=False),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.Integer, nullable=False),
        sa.Column('updated_at', sa.Integer, nullable=False))
    op.create_index('ix_workflow_node_templates_owner_id', 'workflow_node_templates', ['owner_id'])
    op.create_table('workflow_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workflow_id', sa.String(36), nullable=False),
        sa.Column('workflow_version', sa.Integer, nullable=False),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.Column('request_key', sa.String(128), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(4096), nullable=False),
        sa.Column('graph', sa.JSON, nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.Integer, nullable=False),
        sa.UniqueConstraint('created_by', 'request_key', name='uq_workflow_snapshot_request'))
    op.create_index('ix_workflow_snapshots_created_by', 'workflow_snapshots', ['created_by'])


def downgrade():
    op.drop_table('workflow_snapshots')
    op.drop_table('workflow_node_templates')
    op.drop_table('workflow_templates')
