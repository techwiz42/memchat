"""Tests for /api/chat and /api/chat/history endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Message, MessageSource


# ---------- helpers ----------

def _mock_openai_completion(content: str = "Hello from LLM"):
    """Return an object that quacks like ``chat.completions.create()`` result."""
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


# ---------- POST /api/chat ----------

class TestChatPost:
    @pytest.fixture(autouse=True)
    def _patch_externals(self):
        """Patch RAG retrieval, embedding, and LLM client."""
        with (
            patch("api.chat.retrieve_context", new_callable=AsyncMock, return_value="[Memory 1]: ctx") as rc,
            patch("api.chat.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536) as et,
            patch("api.chat.store_embedding", new_callable=AsyncMock) as se,
            patch("api.chat._get_llm_client") as glc,
        ):
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_openai_completion("Test reply")
            )
            glc.return_value = mock_client
            self.retrieve_context = rc
            self.embed_text = et
            self.store_embedding = se
            self.llm_client = mock_client
            yield

    async def test_chat_returns_response(self, test_client, auth_headers):
        resp = await test_client.post(
            "/api/chat", json={"message": "Hi there"}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["response"] == "Test reply"

    async def test_chat_calls_rag(self, test_client, auth_headers, registered_user):
        await test_client.post(
            "/api/chat", json={"message": "Tell me"}, headers=auth_headers
        )
        self.retrieve_context.assert_awaited_once()
        args = self.retrieve_context.call_args
        assert args[0][1] == registered_user["id"]  # user_id
        assert args[0][2] == "Tell me"  # query

    async def test_chat_embeds_exchange(self, test_client, auth_headers):
        await test_client.post(
            "/api/chat", json={"message": "Remember this"}, headers=auth_headers
        )
        self.embed_text.assert_awaited_once()
        self.store_embedding.assert_awaited_once()

    async def test_chat_requires_auth(self, test_client):
        resp = await test_client.post("/api/chat", json={"message": "Hi"})
        assert resp.status_code == 403


# ---------- GET /api/chat/history ----------

class TestChatHistory:
    async def _seed_messages(self, db_session: AsyncSession, user_id: uuid.UUID, count: int):
        base = datetime.now(timezone.utc) - timedelta(minutes=count)
        for i in range(count):
            msg = Message(
                user_id=user_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"msg-{i}",
                source=MessageSource.TEXT,
                created_at=base + timedelta(minutes=i),
            )
            db_session.add(msg)
        await db_session.commit()

    async def test_returns_chronological_order(self, test_client, auth_headers, registered_user, db_session):
        await self._seed_messages(db_session, registered_user["id"], 5)
        resp = await test_client.get("/api/chat/history?limit=50", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5
        # Chronological: first created comes first
        assert data[0]["content"] == "msg-0"
        assert data[-1]["content"] == "msg-4"

    async def test_respects_limit(self, test_client, auth_headers, registered_user, db_session):
        await self._seed_messages(db_session, registered_user["id"], 10)
        resp = await test_client.get("/api/chat/history?limit=3", headers=auth_headers)
        assert len(resp.json()) == 3

    async def test_user_isolation(self, test_client, auth_headers, registered_user, db_session):
        """Messages from another user should not appear."""
        other_id = uuid.uuid4()
        from models.user import User
        from passlib.hash import bcrypt

        other = User(id=other_id, email="other@example.com", hashed_password=bcrypt.hash("x"))
        db_session.add(other)
        msg = Message(user_id=other_id, role="user", content="other-msg", source=MessageSource.TEXT)
        db_session.add(msg)
        await db_session.commit()

        resp = await test_client.get("/api/chat/history?limit=50", headers=auth_headers)
        assert resp.status_code == 200
        # Should only see registered_user's messages (none seeded)
        assert len(resp.json()) == 0
