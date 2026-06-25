from datetime import datetime
from typing import Optional

from src.db.models.base import BaseModelConfig


# Auth request/response models
class RegisterRequest(BaseModelConfig):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModelConfig):
    username: str
    password: str


class ForgotPasswordRequest(BaseModelConfig):
    email: str


class ResetPasswordRequest(BaseModelConfig):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModelConfig):
    current_password: str
    new_password: str


class UpdateProfileRequest(BaseModelConfig):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class AuthResponse(BaseModelConfig):
    token: str
    user_id: str
    username: str


class TokenRefreshResponse(BaseModelConfig):
    token: str


class StatusResponse(BaseModelConfig):
    status: str


class MessageResponse(BaseModelConfig):
    message: str


class SessionData(BaseModelConfig):
    id: str
    user_id: str
    token: str
    expires_at: datetime


class ResetTokenData(BaseModelConfig):
    id: str
    user_id: str
    token: str
    expires_at: datetime
    used_at: Optional[datetime] = None


class ProfileResponse(BaseModelConfig):
    id: str
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
