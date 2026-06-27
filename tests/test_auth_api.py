"""
Интеграционные тесты для auth и profile API endpoints
"""
import pytest
import uuid

from fastapi.testclient import TestClient
from src.db.entity import DBUser
from src.utils.passwords import hash_password


@pytest.mark.integration
@pytest.mark.database
class TestAuthAPI:
    """Тесты auth API endpoints"""

    def test_register_success(self, client: TestClient, db_session):
        """Тест успешной регистрации"""
        response = client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "securepassword123",
                "full_name": "New User",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token"].startswith("lt_")
        assert data["username"] == "newuser"
        assert "user_id" in data

    def test_register_duplicate_username(self, client: TestClient, db_session):
        """Тест регистрации с существующим username"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="existinguser",
            email="existing@example.com",
            password_hash="hash",
        )
        db_session.add(user)
        db_session.commit()

        response = client.post(
            "/api/auth/register",
            json={
                "username": "existinguser",
                "email": "another@example.com",
                "password": "password",
            }
        )

        assert response.status_code == 400
        assert "already taken" in response.json()["detail"]

    def test_login_success(self, client: TestClient, db_session):
        """Тест успешного входа"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="loginuser",
            email="login@example.com",
            password_hash=hash_password("correctpassword"),
        )
        db_session.add(user)
        db_session.commit()

        response = client.post(
            "/api/auth/login",
            json={
                "username": "loginuser",
                "password": "correctpassword",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token"].startswith("lt_")
        assert data["username"] == "loginuser"
        assert data["user_id"] == user.id

    def test_login_invalid_password(self, client: TestClient, db_session):
        """Тест входа с неправильным паролем"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="wrongpwduser",
            email="wrongpwd@example.com",
            password_hash="correctpassword",
        )
        db_session.add(user)
        db_session.commit()

        response = client.post(
            "/api/auth/login",
            json={
                "username": "wrongpwduser",
                "password": "wrongpassword",
            }
        )

        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_login_invalid_username(self, client: TestClient):
        """Тест входа с несуществующим пользователем"""
        response = client.post(
            "/api/auth/login",
            json={
                "username": "nonexistent",
                "password": "anypassword",
            }
        )

        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_logout_without_token(self, client: TestClient):
        """Тест выхода без токена"""
        response = client.post("/api/auth/logout")
        assert response.status_code == 401

    def test_forgot_password_existing_user(self, client: TestClient, db_session):
        """Тест forgot-password для существующего пользователя"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="forgotuser",
            email="forgot@example.com",
            password_hash="hash",
        )
        db_session.add(user)
        db_session.commit()

        response = client.post(
            "/api/auth/forgot-password",
            json={"email": "forgot@example.com"},
        )

        assert response.status_code == 200
        assert "sent" in response.json()["message"]

    def test_forgot_password_nonexistent_user(self, client: TestClient):
        """Тест forgot-password для несуществующего пользователя — не раскрывает info"""
        response = client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )

        assert response.status_code == 200
        assert "sent" in response.json()["message"]

    def test_reset_password_success(self, client: TestClient, db_session, db_repository):
        """Тест успешного сброса пароля"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="resetpwduser",
            email="resetpwd@example.com",
            password_hash="oldpassword",
        )
        db_session.add(user)
        db_session.commit()

        _, token_str = db_repository.create_reset_token(user.id)

        response = client.post(
            "/api/auth/reset-password",
            json={
                "token": token_str,
                "new_password": "newpassword123",
            },
        )

        assert response.status_code == 200
        assert "successfully" in response.json()["message"]

        # verify the new password works for login
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "resetpwduser", "password": "newpassword123"},
        )
        assert login_resp.status_code == 200

    def test_reset_password_invalid_token(self, client: TestClient):
        """Тест сброса пароля с невалидным токеном"""
        response = client.post(
            "/api/auth/reset-password",
            json={
                "token": "invalid_token",
                "new_password": "newpassword",
            },
        )

        assert response.status_code == 400
        assert "Invalid" in response.json()["detail"] or "expired" in response.json()["detail"]

    def test_refresh_with_invalid_token(self, client: TestClient):
        """Тест refresh с невалидным токеном"""
        response = client.post(
            "/api/auth/refresh",
            headers={"X-Auth-Token": "invalid_token"},
        )

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.database
class TestProfileAPI:
    """Тесты profile API endpoints"""

    def _register_and_get_token(self, client: TestClient, username: str) -> tuple[str, str]:
        """Helper: регистрирует пользователя и возвращает (token, user_id)"""
        user_id = str(uuid.uuid4())
        response = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": "password",
                "full_name": f"User {username}",
            },
        )
        data = response.json()
        return data["token"], data["user_id"]

    def test_get_profile_unauthorized(self, client: TestClient):
        """Тест получения профиля без токена"""
        response = client.get("/api/profile")
        assert response.status_code == 401

    def test_get_profile_invalid_token(self, client: TestClient):
        """Тест получения профиля с невалидным токеном"""
        response = client.get(
            "/api/profile",
            headers={"X-Auth-Token": "invalid_token"},
        )
        assert response.status_code == 401

    def test_update_profile_unauthorized(self, client: TestClient):
        """Тест обновления профиля без токена"""
        response = client.put(
            "/api/profile",
            json={"full_name": "Hacker Name"},
        )
        assert response.status_code == 401

    def test_change_password_unauthorized(self, client: TestClient):
        """Тест смены пароля без токена"""
        response = client.put(
            "/api/profile/password",
            json={
                "current_password": "old",
                "new_password": "new",
            },
        )
        assert response.status_code == 401
