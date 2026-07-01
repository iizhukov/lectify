import uuid
from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.entity import DBUser
from src.db.models.user import UserModel
from src.utils.passwords import verify_password


def _user_to_model(user: DBUser) -> UserModel:
    return UserModel(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class UserRepository(BaseRepository):

    def create(
        self,
        user_id: str,
        username: str,
        email: Optional[str] = None,
        password_hash: Optional[str] = None,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> UserModel:
        with self.session() as s:
            user = DBUser(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                full_name=full_name,
                avatar_url=avatar_url,
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            return _user_to_model(user)

    def get(self, user_id: str) -> Optional[UserModel]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.id == user_id).first()
            if not user:
                return None
            return _user_to_model(user)

    def get_by_username(self, username: str) -> Optional[UserModel]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.username == username).first()
            if not user:
                return None
            return _user_to_model(user)

    def get_by_email(self, email: str) -> Optional[UserModel]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.email == email).first()
            if not user:
                return None
            return _user_to_model(user)

    def update(self, user_id: str, **kwargs) -> Optional[UserModel]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.id == user_id).first()
            if not user:
                return None
            for key, value in kwargs.items():
                if hasattr(user, key) and value is not None:
                    setattr(user, key, value)
            s.commit()
            s.refresh(user)
            return _user_to_model(user)

    def verify_credentials(self, username: str, password: str) -> Optional[UserModel]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.username == username).first()
            if not user or not user.password_hash:
                return None
            if not verify_password(password, user.password_hash):
                return None
            return _user_to_model(user)

    def get_or_create_default(self) -> UserModel:
        default_user = self.get_by_username("anonymous")
        if default_user:
            return default_user
        return self.create(user_id=str(uuid.uuid4()), username="anonymous")
