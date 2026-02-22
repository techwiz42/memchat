"""Tests for /api/voice-tools/* (Omnia tool callbacks)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest


class TestRagQuery:
    async def test_valid_query_returns_context(self, test_client, fake_redis, db_session):
        # Create a session token in fake redis
        user_id = uuid.uuid4()
        await fake_redis.setex(f"voice_session:tok-abc", 1800, str(user_id))

        with patch("api.voice_tools.retrieve_context", new_callable=AsyncMock, return_value="[Memory 1]: data"):
            resp = await test_client.post(
                "/api/voice-tools/rag-query",
                json={"query": "What do I like?"},
                headers={"Authorization": "Bearer tok-abc"},
            )
        assert resp.status_code == 200
        assert resp.json()["result"] == "[Memory 1]: data"

    async def test_empty_context_returns_fallback(self, test_client, fake_redis, db_session):
        user_id = uuid.uuid4()
        await fake_redis.setex(f"voice_session:tok-abc", 1800, str(user_id))

        with patch("api.voice_tools.retrieve_context", new_callable=AsyncMock, return_value=""):
            resp = await test_client.post(
                "/api/voice-tools/rag-query",
                json={"query": "Unknown"},
                headers={"Authorization": "Bearer tok-abc"},
            )
        assert resp.status_code == 200
        assert "no relevant" in resp.json()["result"].lower()

    async def test_no_auth_returns_401(self, test_client, db_session):
        resp = await test_client.post(
            "/api/voice-tools/rag-query",
            json={"query": "test"},
        )
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, test_client, fake_redis, db_session):
        resp = await test_client.post(
            "/api/voice-tools/rag-query",
            json={"query": "test"},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


class TestStoreMemory:
    async def test_valid_store(self, test_client, fake_redis, db_session):
        user_id = uuid.uuid4()
        await fake_redis.setex(f"voice_session:tok-xyz", 1800, str(user_id))

        with (
            patch("api.voice_tools.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536),
            patch("api.voice_tools.store_embedding", new_callable=AsyncMock),
        ):
            resp = await test_client.post(
                "/api/voice-tools/store-memory",
                json={"content": "I like pizza"},
                headers={"Authorization": "Bearer tok-xyz"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "stored"

    async def test_no_auth_returns_401(self, test_client, db_session):
        resp = await test_client.post(
            "/api/voice-tools/store-memory",
            json={"content": "test"},
        )
        assert resp.status_code == 401
