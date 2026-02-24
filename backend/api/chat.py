"""Text chat endpoint with RAG-augmented LLM responses and web search tool."""

import json
import uuid
import logging

import tiktoken
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
from search.google_search import web_search
from search.web_fetch import web_fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_TOKEN_BUDGET = 5000
_tokenizer = tiktoken.get_encoding("cl100k_base")
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


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the internet for current information. Use this when the user asks about "
            "recent events, news, current data, or anything that requires up-to-date information "
            "beyond your training data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the internet.",
                },
            },
            "required": ["query"],
        },
    },
}

WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "Fetch and read the content of a web page. Use this when the user provides a URL "
            "to read, or when you need to get the full content of a page found via web_search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to fetch and read.",
                },
            },
            "required": ["url"],
        },
    },
}

MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT_TEMPLATE = """Your name is {agent_name}. Always refer to yourself as {agent_name} when asked your name or when introducing yourself.

You are a helpful personal assistant with access to the user's stored memories and knowledge.
When relevant context from the user's memory is provided, use it to give personalized, informed responses.
If you don't have relevant information in the provided context, say so honestly.

You have access to two internet tools:
- web_search: Search the internet for current information. Use for recent events, news, or real-time data.
- web_fetch: Fetch and read the full content of any web page. Use when the user gives you a URL,
  or when you want to read the full article from a search result.

Do not search for things you can answer confidently from your own knowledge.
When you use search results or fetched content, briefly cite the source.

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

    # Fetch recent conversation history, trimmed to token budget
    recent = await db.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(100)
    )
    recent_msgs = recent.scalars().all()  # newest-first
    token_count = 0
    selected: list[Message] = []
    for msg in recent_msgs:
        msg_tokens = len(_tokenizer.encode(msg.content)) + 4  # +4 for role/framing overhead
        if token_count + msg_tokens > HISTORY_TOKEN_BUDGET:
            break
        token_count += msg_tokens
        selected.append(msg)
    selected.reverse()  # back to chronological order
    for msg in selected:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": body.message})

    # Call LLM with tool-calling loop
    client = _get_llm_client()
    model = user_settings.llm_model
    _restricted = model.startswith("gpt-5") or model.startswith("o")

    llm_kwargs: dict = {
        "model": model,
        "messages": messages,
        "tools": [WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
    }
    # GPT-5 and o-series models only support default temperature
    if not _restricted:
        llm_kwargs["temperature"] = user_settings.llm_temperature
    if user_settings.llm_max_tokens is not None:
        if _restricted:
            llm_kwargs["max_completion_tokens"] = user_settings.llm_max_tokens
        else:
            llm_kwargs["max_tokens"] = user_settings.llm_max_tokens

    assistant_content = None
    for _ in range(MAX_TOOL_ITERATIONS):
        completion = await client.chat.completions.create(**llm_kwargs)
        choice = completion.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            # Append the assistant message with tool calls
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                args = json.loads(tool_call.function.arguments)
                if tool_call.function.name == "web_search":
                    query = args.get("query", "")
                    logger.info(f"LLM invoked web_search for user {user_id}: {query!r}")
                    result = await web_search(query)
                elif tool_call.function.name == "web_fetch":
                    url = args.get("url", "")
                    logger.info(f"LLM invoked web_fetch for user {user_id}: {url!r}")
                    result = await web_fetch(url)
                else:
                    result = f"Unknown tool: {tool_call.function.name}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
        else:
            assistant_content = choice.message.content
            break

    if assistant_content is None:
        assistant_content = "I'm sorry, I wasn't able to complete that request. Please try again."

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
