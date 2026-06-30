"""Auth system: sessions, password reset, extended users

Revision ID: 003
Revises: 002
Create Date: 2024-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    result = conn.execute(
        sa.text(f"SELECT 1 FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{col}'")
    )
    return result.fetchone() is not None


def _idx_exists(conn, idx: str) -> bool:
    result = conn.execute(
        sa.text(f"SELECT 1 FROM pg_indexes WHERE indexname = '{idx}'")
    )
    return result.fetchone() is not None


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(
        sa.text(f"SELECT 1 FROM information_schema.tables WHERE table_name = '{table}'")
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # Extend users table
    if not _col_exists(conn, 'users', 'email'):
        op.add_column('users', sa.Column('email', sa.String(), nullable=True))
    if not _col_exists(conn, 'users', 'password_hash'):
        op.add_column('users', sa.Column('password_hash', sa.String(), nullable=True))
    if not _col_exists(conn, 'users', 'full_name'):
        op.add_column('users', sa.Column('full_name', sa.String(), nullable=True))
    if not _col_exists(conn, 'users', 'avatar_url'):
        op.add_column('users', sa.Column('avatar_url', sa.String(), nullable=True))
    if not _col_exists(conn, 'users', 'is_active'):
        op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))

    if not _idx_exists(conn, 'ix_users_email'):
        op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Sessions table
    if not _table_exists(conn, 'sessions'):
        op.create_table(
            'sessions',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('token', sa.String(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_sessions_id'), 'sessions', ['id'], unique=True)
        op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
        op.create_index(op.f('ix_sessions_token'), 'sessions', ['token'], unique=True)

    # Password reset tokens table
    if not _table_exists(conn, 'password_reset_tokens'):
        op.create_table(
            'password_reset_tokens',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('token', sa.String(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_password_reset_tokens_id'), 'password_reset_tokens', ['id'], unique=True)
        op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
        op.create_index(op.f('ix_password_reset_tokens_token'), 'password_reset_tokens', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_password_reset_tokens_token'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')

    op.drop_index(op.f('ix_sessions_token'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_id'), table_name='sessions')
    op.drop_table('sessions')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'full_name')
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'email')
