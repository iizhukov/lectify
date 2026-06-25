from fastapi import APIRouter, HTTPException, Header

from src.db.repository import Repository
from src.db.models.auth import (
    UpdateProfileRequest,
    ChangePasswordRequest,
    ProfileResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _current_user(x_auth_token: str = Header(None)):
    repo = Repository()
    user = repo.verify_session(x_auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user, repo


@router.get("", response_model=ProfileResponse)
def get_profile(x_auth_token: str = Header(None)):
    user, repo = _current_user(x_auth_token)
    return ProfileResponse.model_validate(user)


@router.put("", response_model=ProfileResponse)
def update_profile(req: UpdateProfileRequest, x_auth_token: str = Header(None)):
    user, repo = _current_user(x_auth_token)
    updated = repo.update(user.id, full_name=req.full_name, avatar_url=req.avatar_url)
    return ProfileResponse.model_validate(updated)


@router.put("/password", response_model=MessageResponse)
def change_password(req: ChangePasswordRequest, x_auth_token: str = Header(None)):
    user, repo = _current_user(x_auth_token)
    if user.password_hash != req.current_password:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    repo.update(user.id, password_hash=req.new_password)
    return MessageResponse(message="Password changed successfully")
