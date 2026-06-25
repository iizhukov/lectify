import uuid

from fastapi import APIRouter, HTTPException, Header

from src.db.repository import Repository
from src.db.models.auth import (
    RegisterRequest,
    LoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    AuthResponse,
    TokenRefreshResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _require_auth(x_auth_token: str = Header(None)) -> str:
    repo = Repository()
    user = repo.verify_session(x_auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_auth_token


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    repo = Repository()

    if repo.get_by_username(req.username):
        raise HTTPException(status_code=400, detail="Username already taken")

    user_id = str(uuid.uuid4())
    user = repo.create(
        user_id=user_id,
        username=req.username,
        email=req.email,
        password_hash=req.password,
        full_name=req.full_name,
    )

    _, token = repo.create_session(user_id)

    return AuthResponse(token=token, user_id=user.id, username=user.username)


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest):
    repo = Repository()

    user = repo.get_by_username(req.username)
    if not user or user.password_hash != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _, token = repo.create_session(user.id)

    return AuthResponse(token=token, user_id=user.id, username=user.username)


@router.post("/logout", response_model=MessageResponse)
def logout(x_auth_token: str = Header(None)):
    if not x_auth_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    repo = Repository()
    repo.delete_session(x_auth_token)
    return MessageResponse(message="Logged out successfully")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(req: ForgotPasswordRequest):
    repo = Repository()

    user = repo.get_by_email(req.email)
    if user:
        repo.create_reset_token(user.id)

    return MessageResponse(message="If the email exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(req: ResetPasswordRequest):
    repo = Repository()

    user = repo.verify_reset_token(req.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    repo.update(user.id, password_hash=req.new_password)
    repo.consume_reset_token(req.token)

    return MessageResponse(message="Password reset successfully")


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh(x_auth_token: str = Header(None)):
    repo = Repository()

    user = repo.verify_session(x_auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    repo.delete_session(x_auth_token)
    _, new_token = repo.create_session(user.id)

    return TokenRefreshResponse(token=new_token)
