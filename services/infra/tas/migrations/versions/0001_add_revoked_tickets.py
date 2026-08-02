"""add_revoked_tickets

Revision ID: 0001
Revises: None
Create Date: 2026-08-02 23:35:10.064536

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
        'revoked_tickets',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column('jti', sa.String(255), nullable=False),
        sa.Column('revoked_at', sa.DateTime, server_default='now()'),
        sa.Column('reason', sa.String(255))
    )


def downgrade() -> None:
    op.drop_table('revoked_tickets')
