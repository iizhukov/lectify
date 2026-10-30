"""Persist launch intent before external container creation."""
from alembic import op
import sqlalchemy as sa

revision = '0003_container_attempts'
down_revision = '0002_node_events'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workflow_container_attempts',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('execution_id', sa.String(36), sa.ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(64), nullable=False),
        sa.Column('fence', sa.BigInteger, nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('image', sa.String(512), nullable=False),
        sa.Column('daemon_id', sa.String(256), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('container_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('execution_id','node_id','fence','role', name='uq_workflow_container_assignment'))


def downgrade():
    op.drop_table('workflow_container_attempts')
