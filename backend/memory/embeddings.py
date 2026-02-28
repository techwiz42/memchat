"""OpenAI embedding generation with optional token tracking."""

import logging
import uuid

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

# Running token counter for embeddings — aggregated and flushed by callers
_pending_embedding_tokens: int = 0


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
    global _pending_embedding_tokens
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=text,
        dimensions=settings.embedding_dimensions,
    )
    if response.usage:
        _pending_embedding_tokens += response.usage.total_tokens
    return response.data[0].embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-generate embedding vectors for multiple texts in one API call.

    Args:
        texts: List of texts to embed.

    Returns:
        List of embedding vectors, one per input text, in the same order.
    """
    global _pending_embedding_tokens
    if not texts:
        return []
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    if response.usage:
        _pending_embedding_tokens += response.usage.total_tokens
    # OpenAI returns embeddings in the same order as input
    return [item.embedding for item in response.data]


async def flush_embedding_tokens(user_id: uuid.UUID) -> None:
    """Persist accumulated embedding token count for this user, then reset."""
    global _pending_embedding_tokens
    tokens = _pending_embedding_tokens
    _pending_embedding_tokens = 0
    if tokens == 0:
        return
    try:
        from models import TokenUsage
        from models.base import async_session_factory
        async with async_session_factory() as session:
            session.add(TokenUsage(
                user_id=user_id,
                model=settings.embedding_model,
                prompt_tokens=tokens,
                completion_tokens=0,
                total_tokens=tokens,
                source="embedding",
            ))
            await session.commit()
    except Exception as e:
        logger.warning("Failed to log embedding token usage: %s", e)
