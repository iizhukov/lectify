"""Entities migration: execution name/date fields, node_name, plugin node_count

Revision ID: 004
Revises: 003
Create Date: 2026-06-26 00:00:00.000000

Adds:
- executions.workflow_name  (nullable string)   — human-readable name for the execution
- executions.file_name      (nullable string)   — name of the input file
- executions.language      (nullable string)   — language code, default 'ru'
- execution_nodes.node_name (nullable string)   — human-readable node label
- plugins.node_count       (nullable integer)  — deprecated, mirrors len(node_templates)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    result = conn.execute(
        sa.text(f"SELECT 1 FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{col}'")
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # executions.workflow_name
    if not _col_exists(conn, 'executions', 'workflow_name'):
        op.add_column('executions', sa.Column('workflow_name', sa.String(), nullable=True))

    # executions.file_name
    if not _col_exists(conn, 'executions', 'file_name'):
        op.add_column('executions', sa.Column('file_name', sa.String(), nullable=True))

    # executions.language
    if not _col_exists(conn, 'executions', 'language'):
        op.add_column(
            'executions',
            sa.Column('language', sa.String(), nullable=True, server_default='ru')
        )

    # execution_nodes.node_name
    if not _col_exists(conn, 'execution_nodes', 'node_name'):
        op.add_column('execution_nodes', sa.Column('node_name', sa.String(), nullable=True))

    # plugins.node_count
    if not _col_exists(conn, 'plugins', 'node_count'):
        op.add_column('plugins', sa.Column('node_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('plugins', 'node_count')
    op.drop_column('execution_nodes', 'node_name')
    op.drop_column('executions', 'language')
    op.drop_column('executions', 'file_name')
    op.drop_column('executions', 'workflow_name')
