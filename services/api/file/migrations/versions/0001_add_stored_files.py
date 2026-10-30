"""Persistent file ownership and object lifecycle."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('stored_files',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(128), nullable=False),
        sa.Column('object_key', sa.String(80), nullable=False, unique=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(128), nullable=False),
        sa.Column('size_bytes', sa.BigInteger, nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_stored_files_owner_id', 'stored_files', ['owner_id'])


def downgrade():
    op.drop_index('ix_stored_files_owner_id', table_name='stored_files')
    op.drop_table('stored_files')
