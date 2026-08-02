"""add_permission_rules

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'permission_rules',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column('source_service', sa.String(255), nullable=False),
        sa.Column('target_service', sa.String(255), nullable=False),
        sa.Column('effect', sa.String(16), nullable=False, server_default='ALLOW'),
        sa.Column('description', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_permission_rules_source_target', 'permission_rules',
                     ['source_service', 'target_service'], unique=True)


def downgrade() -> None:
    op.drop_table('permission_rules')
