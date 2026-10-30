"""Encrypted reset delivery outbox, with replica-safe bounded leases."""
from alembic import op
import sqlalchemy as sa

revision = '0002_reset_delivery'
down_revision = '0001_auth'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_reset_deliveries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('auth_users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('reset_hash', sa.String(64), sa.ForeignKey('auth_password_resets.token_hash', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('token_ciphertext', sa.LargeBinary, nullable=False),
        sa.Column('due_at', sa.Integer, nullable=False),
        sa.Column('lease_until', sa.Integer, nullable=False, server_default='0'),
        sa.Column('lease_owner', sa.String(36), nullable=False, server_default=''),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('delivered_at', sa.Integer, nullable=True))


def downgrade():
    op.drop_table('auth_reset_deliveries')
