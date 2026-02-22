"""Integration tests for memory.vector_store (requires PostgreSQL + pgvector).

Marked as integration — auto-skipped if memchat_test DB is unavailable.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from memory.vector_store import (
    MemoryEmbedding,
    store_embedding,
    similarity_search,
    get_old_embeddings,
    delete_embeddings,
)
from models.user import User

pytestmark = pytest.mark.integration


async def _create_user(session) -> uuid.UUID:
    uid = uuid.uuid4()
    user = User(id=uid, email=f"{uid}@test.com", hashed_password="hash")
    session.add(user)
    await session.commit()
    return uid


class TestStoreEmbedding:
    async def test_store_and_retrieve(self, pg_session):
        uid = await _create_user(pg_session)
        emb = [0.1] * 1536
        record = await store_embedding(pg_session, uid, "Hello world", emb)
        assert record.id is not None
        assert record.content == "Hello world"
        assert record.user_id == uid


class TestSimilaritySearch:
    async def test_ordering(self, pg_session):
        """Closer vectors should rank higher."""
        uid = await _create_user(pg_session)
        # Store two embeddings with different vectors
        close_vec = [1.0] + [0.0] * 1535  # Close to query
        far_vec = [0.0] * 1535 + [1.0]  # Far from query
        await store_embedding(pg_session, uid, "close", close_vec)
        await store_embedding(pg_session, uid, "far", far_vec)

        query = [1.0] + [0.0] * 1535
        results = await similarity_search(pg_session, uid, query, top_k=2)
        assert len(results) == 2
        assert results[0].content == "close"

    async def test_user_isolation(self, pg_session):
        uid_a = await _create_user(pg_session)
        uid_b = await _create_user(pg_session)
        vec = [0.5] * 1536
        await store_embedding(pg_session, uid_a, "user A data", vec)
        await store_embedding(pg_session, uid_b, "user B data", vec)

        results = await similarity_search(pg_session, uid_a, vec, top_k=10)
        assert all(r.user_id == uid_a for r in results)
        assert len(results) == 1


class TestGetOldEmbeddings:
    async def test_returns_old_records(self, pg_session):
        uid = await _create_user(pg_session)
        vec = [0.5] * 1536
        record = await store_embedding(pg_session, uid, "old data", vec)
        # Manually set created_at to 2 days ago
        record.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        await pg_session.commit()

        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        results = await get_old_embeddings(pg_session, uid, before=cutoff)
        assert len(results) == 1
        assert results[0].content == "old data"

    async def test_excludes_recent(self, pg_session):
        uid = await _create_user(pg_session)
        vec = [0.5] * 1536
        await store_embedding(pg_session, uid, "recent data", vec)

        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        results = await get_old_embeddings(pg_session, uid, before=cutoff)
        assert len(results) == 0


class TestDeleteEmbeddings:
    async def test_deletes_by_id(self, pg_session):
        uid = await _create_user(pg_session)
        vec = [0.5] * 1536
        r1 = await store_embedding(pg_session, uid, "to delete", vec)
        r2 = await store_embedding(pg_session, uid, "to keep", vec)

        await delete_embeddings(pg_session, [r1.id])

        remaining = await similarity_search(pg_session, uid, vec, top_k=10)
        assert len(remaining) == 1
        assert remaining[0].id == r2.id

    async def test_empty_list_is_noop(self, pg_session):
        await delete_embeddings(pg_session, [])  # Should not raise
