"""RAG retrieval: embed query → search → format context."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import embed_text
from .vector_store import similarity_search

logger = logging.getLogger(__name__)


async def retrieve_context(db: AsyncSession, user_id: uuid.UUID, query: str, top_k: int = 5) -> str:
    """Retrieve relevant context from the user's memory store.

    Embeds the query, performs similarity search, and formats results
    as a context string suitable for LLM injection.

    Args:
        db: Database session.
        user_id: Owner whose memories to search.
        query: The search query text.
        top_k: Number of context chunks to retrieve.

    Returns:
        Formatted context string, or empty string if no relevant memories found.
    """
    query_embedding = await embed_text(query)
    results = await similarity_search(db, user_id, query_embedding, top_k=top_k)

    if not results:
        return ""

    context_parts = []
    for i, memory in enumerate(results, 1):
        context_parts.append(f"[Memory {i}]: {memory.content}")

    return "\n\n".join(context_parts)
