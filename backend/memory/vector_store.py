"""pgvector CRUD operations with per-user namespace isolation."""

import uuid
import logging
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, select, delete
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from config import settings
from models.base import Base

logger = logging.getLogger(__name__)


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = Column(Vector(settings.embedding_dimensions), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


async def store_embedding(
    db: AsyncSession, user_id: uuid.UUID, content: str, embedding: list[float]
) -> MemoryEmbedding:
    """Store a content embedding for a user.

    Does NOT commit — caller is responsible for transaction management.

    Args:
        db: Database session.
        user_id: Owner of this memory.
        content: The original text content.
        embedding: Pre-computed embedding vector.

    Returns:
        The created MemoryEmbedding record.
    """
    record = MemoryEmbedding(user_id=user_id, content=content, embedding=embedding)
    db.add(record)
    return record


async def similarity_search(
    db: AsyncSession, user_id: uuid.UUID, embedding: list[float], top_k: int = 5
) -> list[MemoryEmbedding]:
    """Find the most similar memories for a user.

    Uses cosine distance for similarity ranking. Always scoped by user_id.

    Args:
        db: Database session.
        user_id: Owner whose memories to search.
        embedding: Query embedding vector.
        top_k: Number of results to return.

    Returns:
        List of MemoryEmbedding records ordered by similarity.
    """
    result = await db.execute(
        select(MemoryEmbedding)
        .where(MemoryEmbedding.user_id == user_id)
        .order_by(MemoryEmbedding.embedding.cosine_distance(embedding))
        .limit(top_k)
    )
    return list(result.scalars().all())


async def get_old_embeddings(
    db: AsyncSession, user_id: uuid.UUID, before: datetime, limit: int = 50
) -> list[MemoryEmbedding]:
    """Fetch old embeddings for summarization.

    Args:
        db: Database session.
        user_id: Owner whose memories to fetch.
        before: Only return embeddings created before this time.
        limit: Max number of embeddings to return.

    Returns:
        List of MemoryEmbedding records.
    """
    result = await db.execute(
        select(MemoryEmbedding)
        .where(MemoryEmbedding.user_id == user_id, MemoryEmbedding.created_at < before)
        .order_by(MemoryEmbedding.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_embeddings(db: AsyncSession, embedding_ids: list[uuid.UUID]) -> None:
    """Delete embeddings by their IDs.

    Does NOT commit — caller is responsible for transaction management.

    Args:
        db: Database session.
        embedding_ids: List of embedding record IDs to delete.
    """
    if not embedding_ids:
        return
    await db.execute(
        delete(MemoryEmbedding).where(MemoryEmbedding.id.in_(embedding_ids))
    )
