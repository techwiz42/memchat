"""Text chat endpoint with RAG-augmented LLM responses."""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from config import settings
from memory.embeddings import embed_text
from memory.rag import retrieve_context
from memory.vector_store import store_embedding
from models import Message, MessageSource, get_db
from api.settings import get_or_create_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

_llm_client: AsyncOpenAI | None = None


def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=settings.llm_api_key)
    return _llm_client


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    source: str
    created_at: str


SYSTEM_PROMPT_TEMPLATE = """Your name is {agent_name}. Always refer to yourself as {agent_name} when asked your name or when introducing yourself.

You are a helpful personal assistant with access to the user's stored memories and knowledge.
When relevant context from the user's memory is provided, use it to give personalized, informed responses.
If you don't have relevant information in the provided context, say so honestly.

You are an intellectually curious conversationalist.
Prioritize insight over summary.
Offer unexpected connections.
Ask one thoughtful follow-up question when appropriate.
Write as if speaking to a founder or philosopher, not a casual user."""


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a text message and get a RAG-augmented LLM response."""
    # Retrieve relevant context from user's memory
    context = await retrieve_context(db, user_id, body.message)

    # Load per-user settings
    user_settings = await get_or_create_settings(db, user_id)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(agent_name=user_settings.agent_name)

    # Build messages for LLM
    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({
            "role": "system",
            "content": f"Relevant context from the user's memory:\n\n{context}",
        })

    # Fetch recent conversation history for continuity
    recent = await db.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history = list(reversed(recent.scalars().all()))
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": body.message})

    # Call LLM
    client = _get_llm_client()
    llm_kwargs: dict = {
        "model": user_settings.llm_model,
        "messages": messages,
        "temperature": user_settings.llm_temperature,
    }
    if user_settings.llm_max_tokens is not None:
        llm_kwargs["max_tokens"] = user_settings.llm_max_tokens
    completion = await client.chat.completions.create(**llm_kwargs)
    assistant_content = completion.choices[0].message.content

    # Store both messages in conversation history
    user_msg = Message(user_id=user_id, role="user", content=body.message, source=MessageSource.TEXT)
    assistant_msg = Message(
        user_id=user_id, role="assistant", content=assistant_content, source=MessageSource.TEXT
    )
    db.add(user_msg)
    db.add(assistant_msg)

    # Embed the exchange for future RAG retrieval
    exchange_text = f"User: {body.message}\nAssistant: {assistant_content}"
    embedding = await embed_text(exchange_text)
    await store_embedding(db, user_id, exchange_text, embedding)

    await db.commit()

    return ChatResponse(response=assistant_content)


@router.get("/history", response_model=list[MessageOut])
async def get_history(
    limit: int = 50,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get recent chat history."""
    result = await db.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(reversed(result.scalars().all()))
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            source=m.source.value,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]
