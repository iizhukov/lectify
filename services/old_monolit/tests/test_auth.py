import pytest
import uuid
from datetime import datetime, timedelta

from src.db.entity import DBUser, DBSession, DBPasswordResetToken


@pytest.mark.integration
@pytest.mark.database
class TestAuthRepositorySessions:
    """Тесты работы с сессиями"""

    def test_create_session(self, db_repository):
        """Тест создания сессии"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="session_user",
            email="session@example.com",
            password_hash="hashed_pwd",
        )

        session, token = db_repository.create_session(user.id)

        assert session is not None
        assert token.startswith("lt_")
        assert len(token) > 40
        assert session.user_id == user.id
        assert session.expires_at > datetime.utcnow()

    def test_verify_session_valid(self, db_repository):
        """Тест верификации валидной сессии"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="verify_user",
            email="verify@example.com",
            password_hash="hashed_pwd",
        )

        _, token = db_repository.create_session(user.id)
        verified_user = db_repository.verify_session(token)

        assert verified_user is not None
        assert verified_user.id == user.id
        assert verified_user.username == user.username

    def test_verify_session_invalid(self, db_repository):
        """Тест верификации несуществующей сессии"""
        result = db_repository.verify_session("invalid_token_lt_abc123")
        assert result is None

    def test_verify_session_expired(self, db_repository, db_session):
        """Тест верификации истёкшей сессии"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="expired_user",
            email="expired@example.com",
            password_hash="hashed_pwd",
        )

        session = DBSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token="lt_expired_token",
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add(session)
        db_session.commit()

        result = db_repository.verify_session("lt_expired_token")
        assert result is None

    def test_delete_session(self, db_repository):
        """Тест удаления сессии"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="delete_session_user",
            email="delete_session@example.com",
            password_hash="hashed_pwd",
        )

        _, token = db_repository.create_session(user.id)
        assert db_repository.verify_session(token) is not None

        deleted = db_repository.delete_session(token)
        assert deleted is True
        assert db_repository.verify_session(token) is None

    def test_delete_session_not_found(self, db_repository):
        """Тест удаления несуществующей сессии"""
        result = db_repository.delete_session("nonexistent_token")
        assert result is False

    def test_delete_all_user_sessions(self, db_repository):
        """Тест удаления всех сессий пользователя"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="multi_session_user",
            email="multi_session@example.com",
            password_hash="hashed_pwd",
        )

        db_repository.create_session(user.id)
        db_repository.create_session(user.id)
        db_repository.create_session(user.id)

        count = db_repository.delete_all_user_sessions(user.id)
        assert count == 3
        existing = db_repository.get_session("fake")
        assert existing is None

    def test_cleanup_expired_sessions(self, db_repository, db_session):
        """Тест очистки истёкших сессий"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="cleanup_user",
            email="cleanup@example.com",
            password_hash="hashed_pwd",
        )

        for i in range(3):
            session = DBSession(
                id=str(uuid.uuid4()),
                user_id=user.id,
                token=f"lt_expired_{i}",
                expires_at=datetime.utcnow() - timedelta(hours=i + 1),
            )
            db_session.add(session)
        db_session.commit()

        count = db_repository.cleanup_expired_sessions()
        assert count == 3

    def test_session_ttl_seven_days(self, db_repository):
        """Тест что срок жизни сессии 7 дней"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="ttl_user",
            email="ttl@example.com",
            password_hash="hashed_pwd",
        )

        _, token = db_repository.create_session(user.id)
        session = db_repository.get_session(token)

        assert session.expires_at <= datetime.utcnow() + timedelta(days=7 + 1)
        assert session.expires_at > datetime.utcnow() + timedelta(days=6)


@pytest.mark.integration
@pytest.mark.database
class TestAuthRepositoryResetTokens:
    """Тесты работы с токенами сброса пароля"""

    def test_create_reset_token(self, db_repository):
        """Тест создания токена сброса пароля"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="reset_user",
            email="reset@example.com",
            password_hash="old_hash",
        )

        token, token_str = db_repository.create_reset_token(user.id)

        assert token is not None
        assert len(token_str) > 40
        assert token.user_id == user.id
        assert token.expires_at > datetime.utcnow()
        assert token.used_at is None

    def test_verify_reset_token_valid(self, db_repository):
        """Тест верификации валидного токена сброса"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="verify_reset_user",
            email="verify_reset@example.com",
            password_hash="old_hash",
        )

        _, token_str = db_repository.create_reset_token(user.id)
        verified_user = db_repository.verify_reset_token(token_str)

        assert verified_user is not None
        assert verified_user.id == user.id

    def test_verify_reset_token_invalid(self, db_repository):
        """Тест верификации невалидного токена"""
        result = db_repository.verify_reset_token("invalid_token_str")
        assert result is None

    def test_verify_reset_token_expired(self, db_repository, db_session):
        """Тест верификации истёкшего токена сброса"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="expired_reset_user",
            email="expired_reset@example.com",
            password_hash="old_hash",
        )

        token = DBPasswordResetToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token="lt_expired_reset_token",
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add(token)
        db_session.commit()

        result = db_repository.verify_reset_token("lt_expired_reset_token")
        assert result is None

    def test_consume_reset_token(self, db_repository):
        """Тест потребления токена сброса пароля"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="consume_user",
            email="consume@example.com",
            password_hash="old_hash",
        )

        _, token_str = db_repository.create_reset_token(user.id)
        consumed = db_repository.consume_reset_token(token_str)

        assert consumed is True

        second_consume = db_repository.consume_reset_token(token_str)
        assert second_consume is False

    def test_consume_reset_token_invalid(self, db_repository):
        """Тест потребления невалидного токена"""
        result = db_repository.consume_reset_token("nonexistent_token")
        assert result is False

    def test_old_tokens_invalidated_on_create(self, db_repository):
        """Тест что старые неиспользованные токены инвалидируются при создании нового"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="old_token_user",
            email="old_token@example.com",
            password_hash="old_hash",
        )

        _, old_token_str = db_repository.create_reset_token(user.id)
        _, new_token_str = db_repository.create_reset_token(user.id)

        old_result = db_repository.consume_reset_token(old_token_str)
        assert old_result is False

        new_result = db_repository.consume_reset_token(new_token_str)
        assert new_result is True

    def test_reset_token_ttl_one_hour(self, db_repository):
        """Тест что срок жизни токена сброса 1 час"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="reset_ttl_user",
            email="reset_ttl@example.com",
            password_hash="old_hash",
        )

        token, _ = db_repository.create_reset_token(user.id)

        assert token.expires_at <= datetime.utcnow() + timedelta(hours=1 + 1)
        assert token.expires_at > datetime.utcnow() + timedelta(minutes=55)

    def test_get_user_by_email(self, db_repository):
        """Тест получения пользователя по email"""
        user = db_repository.create(
            user_id=str(uuid.uuid4()),
            username="email_user",
            email="unique_email@example.com",
            password_hash="hashed_pwd",
        )

        found = db_repository.get_user_by_email("unique_email@example.com")
        assert found is not None
        assert found.id == user.id

    def test_get_user_by_email_not_found(self, db_repository):
        """Тест получения несуществующего пользователя по email"""
        result = db_repository.get_user_by_email("nonexistent@example.com")
        assert result is None
