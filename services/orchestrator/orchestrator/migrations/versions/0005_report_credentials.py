"""Encrypted reporting capability for one execution lease generation."""
from alembic import op
import sqlalchemy as sa

revision = '0005_report_credentials'
down_revision = '0004_execution_credentials'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflow_executions',sa.Column('credentials_required',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.execute(sa.text('UPDATE workflow_executions SET credentials_required = true WHERE EXISTS '
        '(SELECT 1 FROM execution_credentials WHERE execution_credentials.execution_id = workflow_executions.id)'))
    op.add_column('workflow_dispatch',sa.Column('report_token_ciphertext',sa.LargeBinary(),nullable=True))


def downgrade():
    op.drop_column('workflow_dispatch','report_token_ciphertext')
    op.drop_column('workflow_executions','credentials_required')
