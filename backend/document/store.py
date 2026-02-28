"""Database-backed document store for generated/edited downloads."""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import GeneratedDocument

logger = logging.getLogger(__name__)


async def store_document(
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    db: AsyncSession,
) -> str:
    """Persist a generated document and return its ID.

    Args:
        user_id: Owner of the document.
        filename: Original filename (for Content-Disposition).
        data: Raw file bytes.
        db: Async database session.

    Returns:
        A unique document ID (UUID string).
    """
    doc_id = str(uuid.uuid4())
    doc = GeneratedDocument(
        id=doc_id,
        user_id=user_id,
        filename=filename,
        data=data,
    )
    db.add(doc)
    await db.flush()
    return doc_id


async def get_document(
    doc_id: str,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[str, bytes] | None:
    """Retrieve a stored document if it belongs to the user.

    Args:
        doc_id: The document ID returned by store_document.
        user_id: The requesting user's ID.
        db: Async database session.

    Returns:
        (filename, data) tuple, or None if not found / wrong user.
    """
    result = await db.execute(
        select(GeneratedDocument).where(
            GeneratedDocument.id == doc_id,
            GeneratedDocument.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        return None
    return doc.filename, doc.data
