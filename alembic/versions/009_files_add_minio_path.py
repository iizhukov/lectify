"""Add minio_path to files table

Revision ID: 009
Revises: 008
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('files') as batch_op:
        batch_op.add_column(sa.Column('minio_path', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('files') as batch_op:
        batch_op.drop_column('minio_path')
