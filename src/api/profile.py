from fastapi import APIRouter, HTTPException, Header

from src.db.repository import Repository
from src.db.models.auth import (
    UpdateProfileRequest,
    ChangePasswordRequest,
    ProfileResponse,
    MessageResponse,
)
from src.utils.passwords import hash_password, verify_password

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _get_user_from_token(authorization: str = Header(None)):
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else authorization
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    repo = Repository()
    user = repo.verify_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user, repo


@router.get("", response_model=ProfileResponse)
def get_profile(authorization: str = Header(None)):
    user, _ = _get_user_from_token(authorization)
    return ProfileResponse.model_validate(user)


@router.put("", response_model=ProfileResponse)
def update_profile(req: UpdateProfileRequest, authorization: str = Header(None)):
    user, repo = _get_user_from_token(authorization)
    updated = repo.update(user.id, full_name=req.full_name, avatar_url=req.avatar_url)
    return ProfileResponse.model_validate(updated)


@router.put("/password", response_model=MessageResponse)
def change_password(req: ChangePasswordRequest, authorization: str = Header(None)):
    user, repo = _get_user_from_token(authorization)
    db_user = repo.get(user.id)
    if not db_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    raw_hash = _get_password_hash(repo, user.id)
    if not verify_password(req.current_password, raw_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    repo.update(user.id, password_hash=hash_password(req.new_password))
    return MessageResponse(message="Password changed successfully")


def _get_password_hash(repo: Repository, user_id: str) -> str:
    from src.db.entity import DBUser
    from src.db.database import SessionLocal
    with SessionLocal() as s:
        user = s.query(DBUser).filter(DBUser.id == user_id).first()
        return user.password_hash if user else ""
