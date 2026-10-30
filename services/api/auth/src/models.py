from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from generated.db.base import BaseModel


class User(BaseModel):
    __tablename__ = 'auth_users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    security_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Session(BaseModel):
    __tablename__ = 'auth_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('auth_users.id', ondelete='CASCADE'), index=True)
    access_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    access_expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    refresh_expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    security_version: Mapped[int] = mapped_column(Integer, nullable=False)


class PasswordReset(BaseModel):
    __tablename__ = 'auth_password_resets'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('auth_users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    security_version: Mapped[int] = mapped_column(Integer, nullable=False)


class ResetDelivery(BaseModel):
    __tablename__ = 'auth_reset_deliveries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('auth_users.id', ondelete='CASCADE'), unique=True, nullable=False)
    reset_hash: Mapped[str] = mapped_column(ForeignKey('auth_password_resets.token_hash', ondelete='CASCADE'), unique=True)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    due_at: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_until: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(36), default='', nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivered_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
