"""Make execution_nodes.node_template_id nullable

Revision ID: 008
Revises: 007_plugins_add_icon_color
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('execution_nodes') as batch_op:
        batch_op.alter_column('node_template_id', existing_type=sa.String(), nullable=True)


def downgrade():
    with op.batch_alter_table('execution_nodes') as batch_op:
        batch_op.alter_column('node_template_id', existing_type=sa.String(), nullable=False)
