"""Index cursor reads and artifact lookup inside a node attempt."""
from alembic import op
revision='0008_attempt_log_index'
down_revision='0007_execution_details'
branch_labels=None
depends_on=None


def upgrade():
    op.create_index('ix_node_events_attempt_log','workflow_node_events',
        ['execution_id','node_id','fence','kind','sequence'])


def downgrade():
    op.drop_index('ix_node_events_attempt_log',table_name='workflow_node_events')
