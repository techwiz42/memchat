"""Integration test: full RAG pipeline with real pgvector (mock only embed_text).

Marked as integration — auto-skipped if memchat_test DB is unavailable.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from memory.rag import retrieve_context
from memory.vector_store import store_embedding
from models.user import User

pytestmark = pytest.mark.integration


async def _create_user(session) -> uuid.UUID:
    uid = uuid.uuid4()
    user = User(id=uid, email=f"{uid}@test.com", hashed_password="hash")
    session.add(user)
    await session.commit()
    return uid


class TestRagPipeline:
    async def test_stores_and_retrieves(self, pg_session):
        """Store embeddings, then retrieve_context should find them."""
        uid = await _create_user(pg_session)

        # Store a few embeddings with known vectors
        vec1 = [1.0] + [0.0] * 1535
        vec2 = [0.0, 1.0] + [0.0] * 1534
        await store_embedding(pg_session, uid, "I like pizza", vec1)
        await store_embedding(pg_session, uid, "The weather is nice", vec2)

        # When retrieving, embed_text is called for the query.
        # Return a vector close to vec1 so "I like pizza" ranks first.
        with patch("memory.rag.embed_text", new_callable=AsyncMock, return_value=vec1):
            context = await retrieve_context(pg_session, uid, "What food do I like?")

        assert "[Memory 1]: I like pizza" in context
        assert "[Memory 2]: The weather is nice" in context

    async def test_no_memories_returns_empty(self, pg_session):
        uid = await _create_user(pg_session)
        query_vec = [0.5] * 1536
        with patch("memory.rag.embed_text", new_callable=AsyncMock, return_value=query_vec):
            context = await retrieve_context(pg_session, uid, "anything")
        assert context == ""
