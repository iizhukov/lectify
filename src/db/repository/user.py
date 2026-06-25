import uuid
from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.repository.schemas import UserData
from src.db.entity import DBUser


class UserRepository(BaseRepository):

    def create(
        self,
        user_id: str,
        username: str,
        email: Optional[str] = None,
        password_hash: Optional[str] = None,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> UserData:
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
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def get(self, user_id: str) -> Optional[UserData]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.id == user_id).first()
            if not user:
                return None
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def get_by_username(self, username: str) -> Optional[UserData]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.username == username).first()
            if not user:
                return None
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def get_by_email(self, email: str) -> Optional[UserData]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.email == email).first()
            if not user:
                return None
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def update(self, user_id: str, **kwargs) -> Optional[UserData]:
        with self.session() as s:
            user = s.query(DBUser).filter(DBUser.id == user_id).first()
            if not user:
                return None
            for key, value in kwargs.items():
                if hasattr(user, key) and value is not None:
                    setattr(user, key, value)
            s.commit()
            s.refresh(user)
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def get_or_create_default(self) -> UserData:
        default_user = self.get("anonymous")
        if default_user:
            return default_user
        return self.create(user_id=str(uuid.uuid4()), username="anonymous")
