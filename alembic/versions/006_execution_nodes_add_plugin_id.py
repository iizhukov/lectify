"""execution_nodes add plugin_id column

Revision ID: 006
Revises: 005
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = 'c8f68add86f4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('execution_nodes', sa.Column('plugin_id', sa.String(), nullable=True))


def downgrade():
    op.drop_column('execution_nodes', 'plugin_id')
