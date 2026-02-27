"""Document library — list, detail, delete user documents across conversations."""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from models import ConversationDocument, Conversation, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents/library", tags=["document_library"])


class DocumentListItem(BaseModel):
    id: str
    filename: str
    conversation_id: str
    conversation_title: str
    created_at: str
    size: int


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int


class DocumentDetail(BaseModel):
    id: str
    filename: str
    content: str
    sections_json: list | None
    created_at: str


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of user's documents across all conversations."""
    # Count total
    count_result = await db.execute(
        select(func.count()).select_from(ConversationDocument).where(
            ConversationDocument.user_id == user_id
        )
    )
    total = count_result.scalar() or 0

    # Fetch page with conversation title
    offset = (page - 1) * per_page
    result = await db.execute(
        select(
            ConversationDocument.id,
            ConversationDocument.filename,
            ConversationDocument.conversation_id,
            ConversationDocument.created_at,
            func.length(ConversationDocument.content).label("size"),
            Conversation.title.label("conversation_title"),
        )
        .join(Conversation, Conversation.id == ConversationDocument.conversation_id)
        .where(ConversationDocument.user_id == user_id)
        .order_by(ConversationDocument.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()
    return DocumentListResponse(
        items=[
            DocumentListItem(
                id=str(r.id),
                filename=r.filename,
                conversation_id=str(r.conversation_id),
                conversation_title=r.conversation_title,
                created_at=r.created_at.isoformat(),
                size=r.size or 0,
            )
            for r in rows
        ],
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get document details including content (not original_bytes)."""
    result = await db.execute(
        select(ConversationDocument).where(
            ConversationDocument.id == document_id,
            ConversationDocument.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail(
        id=str(doc.id),
        filename=doc.filename,
        content=doc.content,
        sections_json=doc.sections_json,
        created_at=doc.created_at.isoformat(),
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document."""
    result = await db.execute(
        select(ConversationDocument).where(
            ConversationDocument.id == document_id,
            ConversationDocument.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.execute(
        delete(ConversationDocument).where(ConversationDocument.id == document_id)
    )
    await db.commit()
    return {"ok": True}
