import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.repository.schemas import SessionData, ResetTokenData, UserData
from src.db.entity import DBSession, DBPasswordResetToken, DBUser


class AuthRepository(BaseRepository):

    SESSION_TTL_DAYS = 7
    RESET_TOKEN_TTL_HOURS = 1

    # ---- Sessions ----

    def create_session(self, user_id: str) -> tuple[SessionData, str]:
        token = f"lt_{secrets.token_urlsafe(32)}"
        session_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(days=self.SESSION_TTL_DAYS)

        with self.session() as s:
            session = DBSession(
                id=session_id,
                user_id=user_id,
                token=token,
                expires_at=expires_at,
            )
            s.add(session)
            s.commit()
            s.refresh(session)
            return SessionData(
                id=session.id,
                user_id=session.user_id,
                token=session.token,
                expires_at=session.expires_at,
            ), token

    def verify_session(self, token: str) -> Optional[UserData]:
        with self.session() as s:
            session = s.query(DBSession).filter(DBSession.token == token).first()
            if not session:
                return None
            if session.expires_at < datetime.utcnow():
                s.delete(session)
                s.commit()
                return None
            user = session.user
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def get_session(self, token: str) -> Optional[SessionData]:
        with self.session() as s:
            session = s.query(DBSession).filter(DBSession.token == token).first()
            if not session:
                return None
            return SessionData(
                id=session.id,
                user_id=session.user_id,
                token=session.token,
                expires_at=session.expires_at,
            )

    def delete_session(self, token: str) -> bool:
        with self.session() as s:
            session = s.query(DBSession).filter(DBSession.token == token).first()
            if session:
                s.delete(session)
                s.commit()
                return True
            return False

    def delete_all_user_sessions(self, user_id: str) -> int:
        with self.session() as s:
            count = s.query(DBSession).filter(DBSession.user_id == user_id).delete()
            s.commit()
            return count

    def cleanup_expired_sessions(self) -> int:
        with self.session() as s:
            count = (
                s.query(DBSession)
                .filter(DBSession.expires_at < datetime.utcnow())
                .delete()
            )
            s.commit()
            return count

    # ---- Password Reset Tokens ----

    def create_reset_token(self, user_id: str) -> tuple[ResetTokenData, str]:
        token_str = secrets.token_urlsafe(32)
        token_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=self.RESET_TOKEN_TTL_HOURS)

        with self.session() as s:
            s.query(DBPasswordResetToken).filter(
                DBPasswordResetToken.user_id == user_id,
                DBPasswordResetToken.used_at.is_(None),
            ).update({"used_at": datetime.utcnow()})

            token = DBPasswordResetToken(
                id=token_id,
                user_id=user_id,
                token=token_str,
                expires_at=expires_at,
            )
            s.add(token)
            s.commit()
            s.refresh(token)
            return ResetTokenData(
                id=token.id,
                user_id=token.user_id,
                token=token.token,
                expires_at=token.expires_at,
                used_at=token.used_at,
            ), token_str

    def verify_reset_token(self, token_str: str) -> Optional[UserData]:
        with self.session() as s:
            token = (
                s.query(DBPasswordResetToken)
                .filter(
                    DBPasswordResetToken.token == token_str,
                    DBPasswordResetToken.used_at.is_(None),
                )
                .first()
            )
            if not token:
                return None
            if token.expires_at < datetime.utcnow():
                s.delete(token)
                s.commit()
                return None
            user = token.user
            return UserData(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
            )

    def consume_reset_token(self, token_str: str) -> bool:
        with self.session() as s:
            token = (
                s.query(DBPasswordResetToken)
                .filter(
                    DBPasswordResetToken.token == token_str,
                    DBPasswordResetToken.used_at.is_(None),
                )
                .first()
            )
            if not token:
                return False
            if token.expires_at < datetime.utcnow():
                s.delete(token)
                s.commit()
                return False
            token.used_at = datetime.utcnow()
            s.commit()
            return True

    def get_user_by_email(self, email: str) -> Optional[UserData]:
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
