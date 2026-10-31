"""Encrypted execution credentials; encryption keys remain outside the database."""
from alembic import op
import sqlalchemy as sa

revision = '0004_execution_credentials'
down_revision = '0003_container_attempts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('execution_credentials',
        sa.Column('execution_id',sa.String(36),sa.ForeignKey('workflow_executions.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('owner_id',sa.String(64),nullable=False),
        sa.Column('ciphertext',sa.LargeBinary(),nullable=False),
        sa.Column('expires_at',sa.BigInteger(),nullable=False))


def downgrade():
    op.drop_table('execution_credentials')
