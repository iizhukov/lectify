"""alter_created_at_in_permission_rules_alter_updated_at_in_per

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-24 00:52:12.594578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
