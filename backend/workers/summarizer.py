"""Background memory summarization worker.

Periodically fetches old embeddings per user, summarizes them via LLM,
re-embeds the summary, and deletes the old embeddings. This compresses
the user's memory over time while preserving semantic content.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI
from sqlalchemy import select, func

from config import settings
from memory.embeddings import embed_text
from memory.vector_store import MemoryEmbedding, get_old_embeddings, delete_embeddings, store_embedding
from models.base import async_session_factory
from models.user import User

logger = logging.getLogger(__name__)

SUMMARIZE_INTERVAL_SECONDS = 3600  # Run every hour
SUMMARIZE_AGE_HOURS = 24  # Summarize embeddings older than 24 hours
SUMMARIZE_BATCH_SIZE = 20  # Min embeddings to trigger summarization
MAX_CHUNK_SIZE = 10  # Summarize this many at a time

_llm_client: AsyncOpenAI | None = None


def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=settings.llm_api_key)
    return _llm_client


async def _summarize_text(contents: list[str]) -> str:
    """Summarize a batch of memory contents via LLM."""
    combined = "\n\n---\n\n".join(contents)
    client = _get_llm_client()
    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a memory compression assistant. Summarize the following collection "
                    "of conversation memories into a concise, information-dense summary. "
                    "Preserve key facts, preferences, and important details. "
                    "Remove redundancies and conversational fluff. "
                    "Output only the summary, no preamble."
                ),
            },
            {"role": "user", "content": combined},
        ],
    )
    return response.choices[0].message.content


async def _summarize_user_memories(user_id) -> int:
    """Summarize old memories for a single user. Returns count of memories summarized."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SUMMARIZE_AGE_HOURS)

    async with async_session_factory() as db:
        old_memories = await get_old_embeddings(db, user_id, before=cutoff, limit=50)

        if len(old_memories) < SUMMARIZE_BATCH_SIZE:
            return 0

        total_summarized = 0

        # Process in chunks
        for i in range(0, len(old_memories), MAX_CHUNK_SIZE):
            chunk = old_memories[i : i + MAX_CHUNK_SIZE]
            contents = [m.content for m in chunk]

            try:
                summary = await _summarize_text(contents)
                summary_embedding = await embed_text(summary)
                await store_embedding(db, user_id, f"[Summary] {summary}", summary_embedding)
                await delete_embeddings(db, [m.id for m in chunk])
                total_summarized += len(chunk)
                logger.info(f"Summarized {len(chunk)} memories for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to summarize memories for user {user_id}: {e}")
                break

        return total_summarized


async def _run_summarization_cycle():
    """Run one cycle of summarization across all users."""
    async with async_session_factory() as db:
        result = await db.execute(select(User.id))
        user_ids = [row[0] for row in result.all()]

    total = 0
    for user_id in user_ids:
        try:
            count = await _summarize_user_memories(user_id)
            total += count
        except Exception as e:
            logger.error(f"Summarization failed for user {user_id}: {e}")

    if total > 0:
        logger.info(f"Summarization cycle complete: {total} memories summarized across {len(user_ids)} users")


async def _summarizer_loop():
    """Background loop that runs summarization periodically."""
    while True:
        try:
            await _run_summarization_cycle()
        except Exception as e:
            logger.error(f"Summarization cycle error: {e}")
        await asyncio.sleep(SUMMARIZE_INTERVAL_SECONDS)


def start_summarizer():
    """Start the background summarizer as an async task."""
    asyncio.get_event_loop().create_task(_summarizer_loop())
    logger.info("Background summarizer scheduled")
