"""Text chat endpoint with RAG-augmented LLM responses and web search tool."""

import json
import uuid
import logging
from datetime import datetime, timezone

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
from models import Conversation, ConversationDocument, Message, MessageSource, get_db
from api.settings import get_or_create_settings
from search.google_search import web_search
from search.web_fetch import web_fetch
from document.editor import edit_preserving_format
from document.generator import generate_document
from document.store import store_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

SUMMARY_MODEL = "gpt-4o-mini"

HISTORY_TOKEN_BUDGET = 5000
_tokenizer = tiktoken.get_encoding("cl100k_base")
_llm_client: AsyncOpenAI | None = None


def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=settings.llm_api_key)
    return _llm_client


async def _generate_summary(
    client: AsyncOpenAI,
    user_message: str,
    assistant_response: str,
    existing_summary: str | None,
) -> str:
    """Generate a brief conversation summary using a fast, cheap model."""
    if existing_summary:
        prompt = (
            f"Current summary: {existing_summary}\n\n"
            f"New exchange:\nUser: {user_message}\nAssistant: {assistant_response}\n\n"
            "Update the summary to reflect this new exchange. "
            "Keep it to 1-2 concise sentences capturing the key topics discussed so far."
        )
    else:
        prompt = (
            f"User: {user_message}\nAssistant: {assistant_response}\n\n"
            "Write a 1-2 sentence summary of this conversation so far. "
            "Be concise and capture the key topic."
        )
    try:
        resp = await client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Failed to generate conversation summary: %s", e)
        return existing_summary or ""


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str


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

CREATE_DOCUMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "create_document",
        "description": (
            "Create a downloadable document file. Use this when the user asks you to generate, "
            "write, create, or export a document, file, spreadsheet, PDF, or screenplay. "
            "Supported formats: .txt (plain text), .md (Markdown), .csv (spreadsheet), "
            ".pdf (PDF), .docx (Word document), .xlsx (Excel spreadsheet), "
            ".fdx (Final Draft screenplay). "
            "When the user says 'Final Draft' they mean the .fdx screenplay format."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "The filename with extension, e.g. 'report.pdf', 'data.csv', 'screenplay.fdx'. "
                        "The extension determines the output format. "
                        "Use .fdx for Final Draft screenplays."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "The full text content for the document. For CSV/XLSX, use comma-separated "
                        "or tab-separated rows. For FDX (Final Draft), use standard screenplay "
                        "formatting with scene headings (INT./EXT.), character names in ALL CAPS, "
                        "dialogue, action lines, and transitions."
                    ),
                },
            },
            "required": ["filename", "content"],
        },
    },
}

MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT_TEMPLATE = """Your name is {agent_name}. Always refer to yourself as {agent_name} when asked your name or when introducing yourself.

You are a helpful personal assistant with access to the user's stored memories and knowledge.
When relevant context from the user's memory is provided, use it to give personalized, informed responses.
If you don't have relevant information in the provided context, say so honestly.

You have access to these tools:
- web_search: Search the internet for current information. Use for recent events, news, or real-time data.
- web_fetch: Fetch and read the full content of any web page. Use when the user gives you a URL,
  or when you want to read the full article from a search result.
- create_document: Create a downloadable document file. Use when the user asks you to generate,
  write, create, or export a file. Supported formats: .txt, .md, .csv, .pdf, .docx, .xlsx,
  .fdx (Final Draft screenplay). When the user says "Final Draft" they mean .fdx format.
  After creating a document, include the download link in your response using markdown:
  [Download filename](url)

When the user uploads a document and asks you to edit, revise, or modify it, you will have the
full document content in your context. Make the requested changes and use create_document to
provide the complete edited document as a downloadable file. Always include the ENTIRE document
in your output, not just the changed parts.

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
    # Resolve or create conversation
    conv_id: uuid.UUID | None = None
    if body.conversation_id:
        try:
            conv_id = uuid.UUID(body.conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation_id")
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == user_id
            )
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        # Auto-create a new conversation titled from the first message
        title = body.message[:100].strip() or "New Chat"
        conversation = Conversation(user_id=user_id, title=title)
        db.add(conversation)
        await db.flush()
        conv_id = conversation.id

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

    # Load full document content uploaded in this conversation
    doc_result = await db.execute(
        select(ConversationDocument)
        .where(
            ConversationDocument.conversation_id == conv_id,
            ConversationDocument.user_id == user_id,
        )
        .order_by(ConversationDocument.created_at)
    )
    uploaded_docs = doc_result.scalars().all()
    if uploaded_docs:
        doc_parts = []
        for doc in uploaded_docs:
            doc_parts.append(f"--- {doc.filename} ---\n{doc.content}\n--- end {doc.filename} ---")
        doc_context = (
            "The user has uploaded the following document(s) in this conversation. "
            "You have the full content available and can edit it as requested.\n\n"
            + "\n\n".join(doc_parts)
        )
        messages.append({"role": "system", "content": doc_context})

    # Fetch recent conversation history, trimmed to token budget
    recent = await db.execute(
        select(Message)
        .where(Message.user_id == user_id, Message.conversation_id == conv_id)
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
        "tools": [WEB_SEARCH_TOOL, WEB_FETCH_TOOL, CREATE_DOCUMENT_TOOL],
    }
    # GPT-5 and o-series models only support default temperature
    if not _restricted:
        llm_kwargs["temperature"] = user_settings.llm_temperature
    # Determine output token budget.  When the conversation has uploaded
    # documents the LLM must be able to emit the full document inside a
    # create_document tool-call, so we compute a floor based on document size.
    effective_max_tokens = user_settings.llm_max_tokens
    if uploaded_docs:
        total_doc_chars = sum(len(d.content) for d in uploaded_docs)
        # ~3.5 chars per token for English text, plus headroom for JSON framing
        doc_token_floor = int(total_doc_chars / 3.5) + 512
        if effective_max_tokens is None or effective_max_tokens < doc_token_floor:
            effective_max_tokens = doc_token_floor

    if effective_max_tokens is not None:
        if _restricted:
            llm_kwargs["max_completion_tokens"] = effective_max_tokens
        else:
            llm_kwargs["max_tokens"] = effective_max_tokens

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
                elif tool_call.function.name == "create_document":
                    doc_filename = args.get("filename", "document.txt")
                    doc_content = args.get("content", "")
                    logger.info(f"LLM invoked create_document for user {user_id}: {doc_filename!r}")
                    try:
                        # Try format-preserving edit from uploaded original
                        doc_bytes = None
                        out_ext = _get_extension(doc_filename)
                        if uploaded_docs and out_ext:
                            # Find most recent uploaded doc with same extension
                            for udoc in reversed(uploaded_docs):
                                if _get_extension(udoc.filename) == out_ext and udoc.original_bytes:
                                    doc_bytes = edit_preserving_format(
                                        udoc.original_bytes, udoc.filename, doc_content,
                                    )
                                    if doc_bytes:
                                        logger.info("Used format-preserving edit from %r", udoc.filename)
                                    break
                        if doc_bytes is None:
                            doc_bytes = generate_document(doc_filename, doc_content)
                        doc_id = store_document(user_id, doc_filename, doc_bytes)
                        download_url = f"/api/documents/download/{doc_id}"
                        result = (
                            f"Document created successfully. "
                            f"Include this exact markdown link in your response for the user to download it:\n"
                            f"[Download {doc_filename}]({download_url})"
                        )
                    except Exception as e:
                        logger.error(f"create_document failed for {doc_filename!r}: {e}", exc_info=True)
                        result = f"Failed to create document: {e}"
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
    user_msg = Message(
        user_id=user_id, role="user", content=body.message,
        source=MessageSource.TEXT, conversation_id=conv_id,
    )
    assistant_msg = Message(
        user_id=user_id, role="assistant", content=assistant_content,
        source=MessageSource.TEXT, conversation_id=conv_id,
    )
    db.add(user_msg)
    db.add(assistant_msg)

    # Bump conversation updated_at and generate summary
    conversation.updated_at = datetime.now(timezone.utc)
    conversation.summary = await _generate_summary(
        client, body.message, assistant_content, conversation.summary,
    )

    # Embed the exchange for future RAG retrieval
    exchange_text = f"User: {body.message}\nAssistant: {assistant_content}"
    embedding = await embed_text(exchange_text)
    await store_embedding(db, user_id, exchange_text, embedding)

    await db.commit()

    return ChatResponse(response=assistant_content, conversation_id=str(conv_id))


@router.get("/history", response_model=list[MessageOut])
async def get_history(
    limit: int = 50,
    conversation_id: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get recent chat history, optionally filtered by conversation."""
    query = select(Message).where(Message.user_id == user_id)
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation_id")
        query = query.where(Message.conversation_id == conv_uuid)
    result = await db.execute(
        query.order_by(Message.created_at.desc()).limit(limit)
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


def _get_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot."""
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()
