"""Tests for /api/auth/* endpoints: register, login, refresh, /me."""

import pytest


class TestRegister:
    async def test_register_returns_201_with_tokens(self, test_client):
        resp = await test_client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "secret123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_duplicate_email_returns_409(self, test_client, registered_user):
        resp = await test_client.post(
            "/api/auth/register",
            json={"email": registered_user["email"], "password": "other"},
        )
        assert resp.status_code == 409
        assert "already registered" in resp.json()["detail"].lower()


class TestLogin:
    async def test_valid_credentials(self, test_client, registered_user):
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_wrong_password_returns_401(self, test_client, registered_user):
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "wrongpass"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    async def test_unknown_email_returns_401(self, test_client):
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever"},
        )
        assert resp.status_code == 401


class TestRefresh:
    async def test_valid_refresh_token(self, test_client, registered_user):
        # First login to get a refresh token
        login_resp = await test_client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = await test_client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_invalid_refresh_token(self, test_client):
        resp = await test_client.post(
            "/api/auth/refresh",
            json={"refresh_token": "garbage.token.value"},
        )
        assert resp.status_code == 401


class TestGetMe:
    async def test_returns_user_info(self, test_client, auth_headers):
        resp = await test_client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert "id" in data

    async def test_no_auth_returns_403(self, test_client):
        resp = await test_client.get("/api/auth/me")
        assert resp.status_code == 403

    async def test_deleted_user_returns_404(self, test_client, registered_user, db_session):
        """Token valid but user row deleted → 404."""
        from sqlalchemy import delete
        from models.user import User

        await db_session.execute(delete(User).where(User.id == registered_user["id"]))
        await db_session.commit()

        headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
        resp = await test_client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 404
