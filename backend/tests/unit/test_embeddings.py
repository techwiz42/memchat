"""Tests for memory.embeddings.embed_text."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEmbedText:
    async def test_calls_openai_correctly(self):
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch("memory.embeddings._get_client", return_value=mock_client):
            from memory.embeddings import embed_text
            result = await embed_text("Hello world")

        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_awaited_once()
        call_kwargs = mock_client.embeddings.create.call_args.kwargs
        assert call_kwargs["input"] == "Hello world"
        assert call_kwargs["model"] == "text-embedding-3-small"

    async def test_singleton_client(self):
        """_get_client should return the same instance on repeat calls."""
        # Reset the module-level singleton
        import memory.embeddings as mod
        mod._client = None

        with patch("memory.embeddings.AsyncOpenAI") as MockOAI:
            mock_instance = MagicMock()
            MockOAI.return_value = mock_instance
            c1 = mod._get_client()
            c2 = mod._get_client()
            assert c1 is c2
            MockOAI.assert_called_once()

        # Clean up
        mod._client = None
