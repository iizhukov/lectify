"""Restart provenance and durable node attempt history."""
from alembic import op
import sqlalchemy as sa

revision='0007_execution_details'
down_revision='0006_stream_checkpoints'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('workflow_executions',sa.Column('parent_execution_id',sa.String(36),sa.ForeignKey('workflow_executions.id'),nullable=True))
    op.add_column('workflow_executions',sa.Column('restart_key_hash',sa.String(64),nullable=True))
    op.create_table('workflow_node_attempts',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('execution_id',sa.String(36),sa.ForeignKey('workflow_executions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('node_id',sa.String(64),nullable=False),sa.Column('number',sa.Integer(),nullable=False),
        sa.Column('fence',sa.BigInteger(),nullable=False),sa.Column('state',sa.String(32),nullable=False),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),sa.Column('finished_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('error_message',sa.Text(),nullable=True),sa.Column('output_artifacts',sa.JSON(),nullable=False),
        *[sa.Column(name,sa.BigInteger(),nullable=False,server_default='0') for name in
          ('bytes_streamed_in','bytes_streamed_out','chunks_processed','execution_time_ms','log_bytes')],
        sa.Column('logs_truncated',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.UniqueConstraint('execution_id','node_id','number',name='uq_node_attempt_number'),
        sa.UniqueConstraint('execution_id','node_id','fence',name='uq_node_attempt_fence'))
    bind=op.get_bind()
    # Historical container records prove an attempt existed, not its outcome.
    counts={}
    for row in bind.execute(sa.text("SELECT id,execution_id,node_id,fence,created_at FROM workflow_container_attempts WHERE role='plugin' ORDER BY execution_id,node_id,fence,id")).mappings():
        key=(row['execution_id'],row['node_id']); counts[key]=counts.get(key,0)+1
        bind.execute(sa.text("INSERT INTO workflow_node_attempts (id,execution_id,node_id,number,fence,state,started_at,output_artifacts) VALUES (:id,:execution_id,:node_id,:number,:fence,'UNKNOWN',:created_at,'{}')"),dict(row,number=counts[key]))


def downgrade():
    op.drop_table('workflow_node_attempts')
    op.drop_column('workflow_executions','restart_key_hash')
    op.drop_column('workflow_executions','parent_execution_id')
