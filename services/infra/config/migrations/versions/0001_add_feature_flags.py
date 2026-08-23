"""add_feature_flags

Revision ID: 0001
Revises: None
Create Date: 2026-08-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feature_flags',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column('service_name', sa.String(64), nullable=False),
        sa.Column('flag_name', sa.String(128), nullable=False),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_feature_flags_service_name', 'feature_flags', ['service_name'])
    op.create_unique_constraint('uq_feature_flags_service_flag', 'feature_flags',
                                ['service_name', 'flag_name'])


def downgrade() -> None:
    op.drop_index('ix_feature_flags_service_name', table_name='feature_flags')
    op.drop_table('feature_flags')
