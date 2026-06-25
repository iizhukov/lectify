from datetime import datetime
from typing import Optional

from src.db.models.base import BaseModelConfig


class UserModel(BaseModelConfig):
    id: str
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileModel(UserModel):
    """User profile model with all editable fields"""
    pass
