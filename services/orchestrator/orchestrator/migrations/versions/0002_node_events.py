"""Execution-scoped reporting capabilities and durable idempotent node events."""
from alembic import op
import sqlalchemy as sa

revision = '0002_node_events'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflow_dispatch', sa.Column('report_token_hash', sa.String(64), nullable=True))
    op.add_column('workflow_dispatch', sa.Column('report_token_fence', sa.BigInteger, nullable=True))
    op.create_table('workflow_node_events',
        sa.Column('sequence', sa.BigInteger().with_variant(sa.Integer, 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('execution_id', sa.String(36), sa.ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(64), nullable=False),
        sa.Column('event_id', sa.String(128), nullable=False),
        sa.Column('owner', sa.String(128), nullable=False),
        sa.Column('fence', sa.BigInteger, nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('execution_id','event_id', name='uq_workflow_node_event_id'))
    op.create_index('ix_workflow_node_events_execution_sequence', 'workflow_node_events', ['execution_id','sequence'])


def downgrade():
    op.drop_table('workflow_node_events')
    with op.batch_alter_table('workflow_dispatch') as batch:
        batch.drop_column('report_token_fence')
        batch.drop_column('report_token_hash')
