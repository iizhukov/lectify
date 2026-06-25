"""
Интеграционные тесты для auth и profile API endpoints
"""
import pytest
import uuid

from fastapi.testclient import TestClient
from src.db.entity import DBUser


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
            password_hash="correctpassword",
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

    def test_logout_success(self, client: TestClient, db_session):
        """Тест успешного выхода"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="logoutuser",
            email="logout@example.com",
            password_hash="password",
        )
        db_session.add(user)
        db_session.commit()

        login_response = client.post(
            "/api/auth/login",
            json={"username": "logoutuser", "password": "password"},
        )
        token = login_response.json()["token"]

        response = client.post(
            "/api/auth/logout",
            headers={"X-Auth-Token": token},
        )

        assert response.status_code == 200
        assert "Logged out" in response.json()["message"]

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

        updated_user = db_session.query(DBUser).filter(DBUser.id == user.id).first()
        assert updated_user.password_hash == "newpassword123"

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

    def test_refresh_success(self, client: TestClient, db_session):
        """Тест успешного refresh токена"""
        user = DBUser(
            id=str(uuid.uuid4()),
            username="refreshuser",
            email="refresh@example.com",
            password_hash="password",
        )
        db_session.add(user)
        db_session.commit()

        login_response = client.post(
            "/api/auth/login",
            json={"username": "refreshuser", "password": "password"},
        )
        old_token = login_response.json()["token"]

        response = client.post(
            "/api/auth/refresh",
            headers={"X-Auth-Token": old_token},
        )

        assert response.status_code == 200
        new_token = response.json()["token"]
        assert new_token != old_token
        assert new_token.startswith("lt_")

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

    def test_get_profile_success(self, client: TestClient, db_session):
        """Тест получения профиля"""
        token, user_id = self._register_and_get_token(client, "profileuser")

        response = client.get(
            "/api/profile",
            headers={"X-Auth-Token": token},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "profileuser"
        assert data["email"] == "profileuser@example.com"
        assert data["full_name"] == "User profileuser"
        assert data["is_active"] is True

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

    def test_update_profile_success(self, client: TestClient, db_session):
        """Тест обновления профиля"""
        token, user_id = self._register_and_get_token(client, "updateprofileuser")

        response = client.put(
            "/api/profile",
            headers={"X-Auth-Token": token},
            json={
                "full_name": "Updated Name",
                "avatar_url": "https://example.com/avatar.png",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Updated Name"
        assert data["avatar_url"] == "https://example.com/avatar.png"

        updated_user = db_session.query(DBUser).filter(DBUser.id == user_id).first()
        assert updated_user.full_name == "Updated Name"
        assert updated_user.avatar_url == "https://example.com/avatar.png"

    def test_update_profile_partial(self, client: TestClient, db_session):
        """Тест частичного обновления профиля (только full_name)"""
        token, user_id = self._register_and_get_token(client, "partialupdateuser")
        initial_avatar = "https://example.com/initial.png"

        client.put(
            "/api/profile",
            headers={"X-Auth-Token": token},
            json={"avatar_url": initial_avatar},
        )

        response = client.put(
            "/api/profile",
            headers={"X-Auth-Token": token},
            json={"full_name": "New Name"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "New Name"
        assert data["avatar_url"] == initial_avatar

    def test_update_profile_unauthorized(self, client: TestClient):
        """Тест обновления профиля без токена"""
        response = client.put(
            "/api/profile",
            json={"full_name": "Hacker Name"},
        )
        assert response.status_code == 401

    def test_change_password_success(self, client: TestClient, db_session):
        """Тест успешной смены пароля"""
        token, user_id = self._register_and_get_token(client, "changepwduser")

        response = client.put(
            "/api/profile/password",
            headers={"X-Auth-Token": token},
            json={
                "current_password": "password",
                "new_password": "newsecurepassword",
            },
        )

        assert response.status_code == 200
        assert "successfully" in response.json()["message"]

        updated_user = db_session.query(DBUser).filter(DBUser.id == user_id).first()
        assert updated_user.password_hash == "newsecurepassword"

        login_response = client.post(
            "/api/auth/login",
            json={
                "username": "changepwduser",
                "password": "newsecurepassword",
            },
        )
        assert login_response.status_code == 200

    def test_change_password_wrong_current(self, client: TestClient, db_session):
        """Тест смены пароля с неправильным текущим паролем"""
        token, user_id = self._register_and_get_token(client, "wrongcurrentuser")

        response = client.put(
            "/api/profile/password",
            headers={"X-Auth-Token": token},
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword",
            },
        )

        assert response.status_code == 400
        assert "incorrect" in response.json()["detail"]

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
