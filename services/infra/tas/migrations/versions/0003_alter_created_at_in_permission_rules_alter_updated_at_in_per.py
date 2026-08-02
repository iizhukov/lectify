"""alter_created_at_in_permission_rules_alter_updated_at_in_per

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-03 00:19:22.533046

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
