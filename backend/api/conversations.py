"""Conversations CRUD — list, create, delete user conversations."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from models import Conversation, Message, get_db

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List user's conversations ordered by most recently updated."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    return [
        ConversationOut(
            id=str(c.id),
            title=c.title,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in conversations
    ]


@router.post("", response_model=ConversationOut)
async def create_conversation(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty conversation."""
    conv = Conversation(user_id=user_id, title="New Chat")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        id=str(conv.id),
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and its messages. RAG embeddings are preserved."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete messages belonging to this conversation
    await db.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await db.delete(conv)
    await db.commit()
    return {"ok": True}
