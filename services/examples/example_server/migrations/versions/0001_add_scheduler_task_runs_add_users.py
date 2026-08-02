"""add_scheduler_task_runs_add_users

Revision ID: 0001
Revises: None
Create Date: 2026-08-02 19:23:22.310278

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
        'scheduler_task_runs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column('task_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error', sa.Text),
        sa.Column('run_count', sa.Integer, server_default='0'),
        sa.Column('started_at', sa.DateTime, server_default='now()')
    )
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column('username', sa.String(50), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(100), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='True'),
        sa.Column('created_at', sa.DateTime, nullable=False)
    )


def downgrade() -> None:
    op.drop_table('scheduler_task_runs')
    op.drop_table('users')
