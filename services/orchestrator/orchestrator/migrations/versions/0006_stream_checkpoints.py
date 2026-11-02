"""Durable node output frames for replay after pause, retry and owner failure."""
from alembic import op
import sqlalchemy as sa

revision = '0006_stream_checkpoints'
down_revision = '0005_report_credentials'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflow_executions',sa.Column('automatic_retries',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('workflow_container_attempts',sa.Column('cleanup_checked_at',sa.BigInteger(),nullable=False,server_default='0'))
    op.add_column('workflow_node_executions',sa.Column('checkpoint_ready',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('workflow_node_executions',sa.Column('automatic_retries',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('workflow_stream_checkpoint_frames',
        sa.Column('execution_id',sa.String(36),sa.ForeignKey('workflow_executions.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('node_id',sa.String(64),primary_key=True),
        sa.Column('position',sa.Integer(),primary_key=True),
        sa.Column('stream_name',sa.String(64),nullable=False),
        sa.Column('sequence',sa.BigInteger(),nullable=False),
        sa.Column('payload',sa.LargeBinary(),nullable=False),
        sa.Column('is_last',sa.Boolean(),nullable=False),
        sa.Column('frame_metadata',sa.JSON(),nullable=False))


def downgrade():
    op.drop_table('workflow_stream_checkpoint_frames')
    op.drop_column('workflow_node_executions','checkpoint_ready')
    op.drop_column('workflow_node_executions','automatic_retries')
    op.drop_column('workflow_container_attempts','cleanup_checked_at')
    op.drop_column('workflow_executions','automatic_retries')
