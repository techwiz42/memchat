"""Memory CRUD — list, search, add, delete user memories (RAG embeddings)."""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from memory.embeddings import embed_text
from memory.vector_store import MemoryEmbedding, store_embedding, similarity_search
from models import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryOut(BaseModel):
    id: str
    content: str
    created_at: str


class MemoryListResponse(BaseModel):
    items: list[MemoryOut]
    total: int


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of user memories (most recent first)."""
    # Count total
    count_result = await db.execute(
        select(func.count()).select_from(MemoryEmbedding).where(
            MemoryEmbedding.user_id == user_id
        )
    )
    total = count_result.scalar() or 0

    # Fetch page (select only non-vector columns)
    offset = (page - 1) * per_page
    result = await db.execute(
        select(MemoryEmbedding.id, MemoryEmbedding.content, MemoryEmbedding.created_at)
        .where(MemoryEmbedding.user_id == user_id)
        .order_by(MemoryEmbedding.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()
    return MemoryListResponse(
        items=[
            MemoryOut(id=str(r.id), content=r.content, created_at=r.created_at.isoformat())
            for r in rows
        ],
        total=total,
    )


@router.get("/search", response_model=list[MemoryOut])
async def search_memories(
    q: str = Query(..., min_length=1, max_length=500),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search across user memories using vector similarity."""
    query_embedding = await embed_text(q)
    results = await similarity_search(db, user_id, query_embedding, top_k=20)
    return [
        MemoryOut(id=str(m.id), content=m.content, created_at=m.created_at.isoformat())
        for m in results
    ]


@router.post("", response_model=MemoryOut)
async def add_memory(
    body: MemoryCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Add a new memory (embed and store)."""
    embedding = await embed_text(body.content)
    record = await store_embedding(db, user_id, body.content, embedding)
    await db.commit()
    await db.refresh(record)
    return MemoryOut(
        id=str(record.id),
        content=record.content,
        created_at=record.created_at.isoformat(),
    )


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single memory."""
    result = await db.execute(
        select(MemoryEmbedding).where(
            MemoryEmbedding.id == memory_id,
            MemoryEmbedding.user_id == user_id,
        )
    )
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.execute(
        delete(MemoryEmbedding).where(MemoryEmbedding.id == memory_id)
    )
    await db.commit()
    return {"ok": True}
