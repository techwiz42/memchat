"""Tests for workers.summarizer."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workers.summarizer import (
    _summarize_text,
    _summarize_user_memories,
    SUMMARIZE_BATCH_SIZE,
    MAX_CHUNK_SIZE,
)


def _mock_completion(content: str):
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _make_memory(content: str, mem_id=None):
    m = MagicMock()
    m.id = mem_id or uuid.uuid4()
    m.content = content
    return m


class TestSummarizeText:
    async def test_calls_llm_with_combined_content(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_completion("Summary of memories")
        )
        with patch("workers.summarizer._get_llm_client", return_value=mock_client):
            result = await _summarize_text(["Memory A", "Memory B"])

        assert result == "Summary of memories"
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        # User message should contain both memories joined by separator
        user_msg = messages[1]["content"]
        assert "Memory A" in user_msg
        assert "Memory B" in user_msg
        assert "---" in user_msg


class TestSummarizeUserMemories:
    @pytest.fixture(autouse=True)
    def _patch(self):
        with (
            patch("workers.summarizer.async_session_factory") as asf,
            patch("workers.summarizer.get_old_embeddings", new_callable=AsyncMock) as goe,
            patch("workers.summarizer.delete_embeddings", new_callable=AsyncMock) as de,
            patch("workers.summarizer.store_embedding", new_callable=AsyncMock) as se,
            patch("workers.summarizer.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536) as et,
            patch("workers.summarizer._get_llm_client") as glc,
        ):
            # Mock the session context manager
            mock_session = AsyncMock()
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            asf.return_value = mock_cm

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_completion("Compressed summary")
            )
            glc.return_value = mock_client

            self.get_old_embeddings = goe
            self.delete_embeddings = de
            self.store_embedding = se
            self.embed_text = et
            self.mock_session = mock_session
            yield

    async def test_skips_if_below_batch_size(self):
        memories = [_make_memory(f"m-{i}") for i in range(SUMMARIZE_BATCH_SIZE - 1)]
        self.get_old_embeddings.return_value = memories
        uid = uuid.uuid4()
        count = await _summarize_user_memories(uid)
        assert count == 0
        self.store_embedding.assert_not_awaited()

    async def test_processes_batch(self):
        memories = [_make_memory(f"m-{i}") for i in range(SUMMARIZE_BATCH_SIZE)]
        self.get_old_embeddings.return_value = memories
        uid = uuid.uuid4()
        count = await _summarize_user_memories(uid)
        assert count == SUMMARIZE_BATCH_SIZE
        # Should call store_embedding for each chunk
        expected_chunks = (SUMMARIZE_BATCH_SIZE + MAX_CHUNK_SIZE - 1) // MAX_CHUNK_SIZE
        assert self.store_embedding.await_count == expected_chunks

    async def test_summary_has_prefix(self):
        memories = [_make_memory(f"m-{i}") for i in range(SUMMARIZE_BATCH_SIZE)]
        self.get_old_embeddings.return_value = memories
        await _summarize_user_memories(uuid.uuid4())
        # Check that stored content has [Summary] prefix
        stored_content = self.store_embedding.call_args_list[0][0][2]
        assert stored_content.startswith("[Summary]")

    async def test_error_stops_processing(self):
        memories = [_make_memory(f"m-{i}") for i in range(SUMMARIZE_BATCH_SIZE + MAX_CHUNK_SIZE)]
        self.get_old_embeddings.return_value = memories
        # Make embed_text fail on second call
        self.embed_text.side_effect = [([0.1] * 1536), Exception("API error")]
        uid = uuid.uuid4()
        count = await _summarize_user_memories(uid)
        # Only first chunk should succeed
        assert count == MAX_CHUNK_SIZE
