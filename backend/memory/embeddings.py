"""OpenAI embedding generation."""

import logging

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.embedding_api_key)
    return _client


async def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text.

    Args:
        text: The text to embed.

    Returns:
        Embedding vector as list of floats.
    """
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=text,
        dimensions=settings.embedding_dimensions,
    )
    return response.data[0].embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-generate embedding vectors for multiple texts in one API call.

    Args:
        texts: List of texts to embed.

    Returns:
        List of embedding vectors, one per input text, in the same order.
    """
    if not texts:
        return []
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    # OpenAI returns embeddings in the same order as input
    return [item.embedding for item in response.data]
