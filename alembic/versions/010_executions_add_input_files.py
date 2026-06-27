"""Add input_files to executions table

Revision ID: 010
Revises: 009
Create Date: 2026-06-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('executions') as batch_op:
        batch_op.add_column(sa.Column('input_files', postgresql.JSON(astext_type=sa.Text()), nullable=True))
        batch_op.alter_column('file_id', existing_type=sa.String(), nullable=True)


def downgrade():
    with op.batch_alter_table('executions') as batch_op:
        batch_op.drop_column('input_files')
        batch_op.alter_column('file_id', existing_type=sa.String(), nullable=False)
