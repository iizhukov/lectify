"""Value objects returned by repository methods — safe from DetachedInstanceError."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserData:
    id: str
    username: str
    email: str | None
    password_hash: str | None
    full_name: str | None
    avatar_url: str | None


@dataclass
class SessionData:
    id: str
    user_id: str
    token: str
    expires_at: datetime


@dataclass
class ResetTokenData:
    id: str
    user_id: str
    token: str
    expires_at: datetime
    used_at: datetime | None
