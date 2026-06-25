"""plugins add color and icon_svg columns

Revision ID: 007
Revises: 006
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plugins', sa.Column('color', sa.String(), nullable=True))
    op.add_column('plugins', sa.Column('icon_svg', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('plugins', 'icon_svg')
    op.drop_column('plugins', 'color')
