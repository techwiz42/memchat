"""Tests for memory.rag.retrieve_context."""

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest


def _make_memory(content: str):
    m = MagicMock()
    m.content = content
    return m


class TestRetrieveContext:
    @pytest.fixture(autouse=True)
    def _patch(self):
        with (
            patch("memory.rag.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536) as et,
            patch("memory.rag.similarity_search", new_callable=AsyncMock) as ss,
        ):
            self.embed_text = et
            self.similarity_search = ss
            yield

    async def test_formats_context(self):
        self.similarity_search.return_value = [
            _make_memory("First fact"),
            _make_memory("Second fact"),
        ]
        from memory.rag import retrieve_context
        db = AsyncMock()
        uid = uuid.uuid4()
        result = await retrieve_context(db, uid, "query text")
        assert "[Memory 1]: First fact" in result
        assert "[Memory 2]: Second fact" in result

    async def test_empty_results(self):
        self.similarity_search.return_value = []
        from memory.rag import retrieve_context
        db = AsyncMock()
        result = await retrieve_context(db, uuid.uuid4(), "query")
        assert result == ""

    async def test_top_k_passthrough(self):
        self.similarity_search.return_value = []
        from memory.rag import retrieve_context
        db = AsyncMock()
        uid = uuid.uuid4()
        await retrieve_context(db, uid, "q", top_k=10)
        self.similarity_search.assert_awaited_once()
        call_kwargs = self.similarity_search.call_args
        assert call_kwargs.kwargs.get("top_k") == 10 or call_kwargs[0][3] == 10

    async def test_embeds_query(self):
        self.similarity_search.return_value = []
        from memory.rag import retrieve_context
        db = AsyncMock()
        await retrieve_context(db, uuid.uuid4(), "test query")
        self.embed_text.assert_awaited_once_with("test query")
