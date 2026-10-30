"""Persistent users, opaque sessions, and single-use password resets."""
from alembic import op
import sqlalchemy as sa

revision = '0001_auth'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('username', sa.String(64), nullable=False, unique=True),
        sa.Column('email', sa.String(254), nullable=False, unique=True),
        sa.Column('full_name', sa.String(256), nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('is_admin', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('security_version', sa.Integer, nullable=False, server_default='0'))
    op.create_table('auth_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('auth_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('access_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('refresh_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('access_expires_at', sa.Integer, nullable=False),
        sa.Column('refresh_expires_at', sa.Integer, nullable=False),
        sa.Column('security_version', sa.Integer, nullable=False))
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_table('auth_password_resets',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('auth_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('expires_at', sa.Integer, nullable=False),
        sa.Column('security_version', sa.Integer, nullable=False))
    op.create_index('ix_auth_password_resets_user_id', 'auth_password_resets', ['user_id'])


def downgrade():
    op.drop_table('auth_password_resets')
    op.drop_table('auth_sessions')
    op.drop_table('auth_users')
