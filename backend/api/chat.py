"""Text chat endpoint with RAG-augmented LLM responses and web search tool."""

import asyncio
import json
import re
import uuid
import logging
from datetime import datetime, timezone

import tiktoken
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from config import settings
from memory.embeddings import embed_text, embed_texts, flush_embedding_tokens
from memory.rag import retrieve_context
from memory.vector_store import MemoryEmbedding
from models import Conversation, ConversationDocument, Message, MessageSource, TokenUsage, get_db
from models.base import async_session_factory
from api.settings import get_or_create_settings
from search.google_search import web_search
from search.web_fetch import web_fetch
from document.editor import (
    edit_preserving_format,
    edit_fdx_section,
    find_replace_fdx,
    edit_text_section,
    find_replace_text,
    edit_docx_section,
    find_replace_docx,
    edit_rich_section,
    find_replace_rich,
)
from document.parser import extract_text_sync
from document.generator import generate_document
from document.scene_splitter import split_fdx_into_scenes, split_large_text, build_table_of_contents
from document.store import store_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

SUMMARY_MODEL = "gpt-4o-mini"

_tokenizer = tiktoken.get_encoding("cl100k_base")


async def _log_token_usage(
    user_id: uuid.UUID,
    model: str,
    usage,
    source: str = "chat",
) -> None:
    """Persist an LLM usage record in a fresh DB session (fire-and-forget safe)."""
    if usage is None:
        return
    try:
        async with async_session_factory() as session:
            session.add(TokenUsage(
                user_id=user_id,
                model=model,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                source=source,
            ))
            await session.commit()
    except Exception as e:
        logger.warning("Failed to log token usage: %s", e)
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
        return resp.choices[0].message.content.strip(), resp.usage
    except Exception as e:
        logger.warning("Failed to generate conversation summary: %s", e)
        return existing_summary or "", None


async def _extract_memories(
    client: AsyncOpenAI,
    user_message: str,
    assistant_response: str,
) -> list[str]:
    """Extract significant memorable facts from a conversation exchange.

    Uses a fast model to identify personal details, preferences, decisions,
    project context, and other facts worth remembering. Returns an empty list
    for trivial exchanges (greetings, chitchat).
    """
    prompt = (
        "You are a memory extraction system. Analyze the following conversation exchange "
        "and extract significant facts that a person would naturally remember about the user.\n\n"
        "Extract facts like:\n"
        "- Personal details (name, location, occupation, age)\n"
        "- Preferences and opinions\n"
        "- Decisions made or plans stated\n"
        "- Project/work context (project names, technologies, goals)\n"
        "- Technical details and specifications discussed\n"
        "- Life events, milestones, or circumstances mentioned\n"
        "- Goals, aspirations, or problems they're working on\n"
        "- Relationships or people mentioned\n\n"
        "Rules:\n"
        "- Each fact should be a concise, standalone statement (one sentence)\n"
        "- Write facts from a third-person perspective about the user (e.g. 'User is working on...')\n"
        "- Skip trivial pleasantries, meta-conversation, and generic chitchat\n"
        "- If there is nothing significant to remember, return an empty array\n"
        "- Return ONLY a JSON array of strings, no other text\n\n"
        f"User: {user_message}\n"
        f"Assistant: {assistant_response}\n\n"
        "Extracted memories (JSON array):"
    )
    try:
        resp = await client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        usage = resp.usage
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        memories = json.loads(raw)
        if isinstance(memories, list):
            return [m for m in memories if isinstance(m, str) and m.strip()], usage
        return [], usage
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to extract memories: %s", e)
        return [], None


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

EDIT_DOCUMENT_SECTION_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_document_section",
        "description": (
            "Edit a specific section of a large uploaded document (screenplay, long text). "
            "Use this instead of create_document when the document has been split into sections. "
            "You can see the table of contents and section numbers in your context. "
            "First use get_document_section to read the section, then use this tool to edit it. "
            "Only provide the content for the ONE section you are editing — the rest of the "
            "document is preserved automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section_index": {
                    "type": "integer",
                    "description": "The section number from the table of contents to edit.",
                },
                "new_content": {
                    "type": "string",
                    "description": (
                        "The complete new text for this section. Include all lines — "
                        "scene heading, action, character names, dialogue, etc. "
                        "Only include content for this one section."
                    ),
                },
            },
            "required": ["section_index", "new_content"],
        },
    },
}

GET_DOCUMENT_SECTION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_document_section",
        "description": (
            "Retrieve the full text of a specific section from a large uploaded document. "
            "Use this to read a section before editing it, or when the user asks about "
            "a specific part of the document. Refer to the table of contents for section numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section_index": {
                    "type": "integer",
                    "description": "The section number from the table of contents to retrieve.",
                },
            },
            "required": ["section_index"],
        },
    },
}

FIND_REPLACE_DOCUMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "find_replace_document",
        "description": (
            "Global find-and-replace across the entire uploaded document. "
            "Use this for bulk changes like renaming a character, fixing a recurring "
            "typo, or replacing a word/phrase throughout. Much faster than editing "
            "individual sections. Case-insensitive by default."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "find": {
                    "type": "string",
                    "description": "The exact text to find (e.g. a character name, word, or phrase).",
                },
                "replace": {
                    "type": "string",
                    "description": "The replacement text.",
                },
            },
            "required": ["find", "replace"],
        },
    },
}

MAX_TOOL_ITERATIONS = 256

SYSTEM_PROMPT_CONVERSATION = """Your name is {agent_name}. Always refer to yourself as {agent_name} when asked your name or when introducing yourself.

You are a helpful personal assistant with access to the user's stored memories and knowledge.
When relevant context from the user's memory is provided, use it to give personalized, informed responses.
If you don't have relevant information in the provided context, say so honestly.

You are not optimized for safety through blandness.

If the user's question contains implicit assumptions, identify them before answering.

For abstract or philosophical topics:
1. Identify hidden assumptions in the user's framing.
2. Surface tensions, contradictions, or tradeoffs.
3. Explore at least one perspective the user may disagree with.
4. Connect ideas across domains when relevant (e.g., psychology, economics, philosophy, systems theory).
5. Synthesize only after exploration.

Do not be contrarian for sport.
Be precise, but willing to destabilize shallow certainty.
When appropriate, ask one question that deepens the inquiry rather than narrows it.

Do not mention this process explicitly unless asked.
Do not search for things you can answer confidently from your own knowledge.
When you use search results or fetched content, briefly cite the source.

You are an intellectually curious conversationalist.
Prioritize insight over summary.
Offer unexpected connections.
Write as if speaking to a founder or philosopher, not a casual user."""

SYSTEM_PROMPT_TASK = SYSTEM_PROMPT_CONVERSATION + """

You have access to these tools:
- web_search: Search the internet for current information. Use for recent events, news, or real-time data.
- web_fetch: Fetch and read the full content of any web page. Use when the user gives you a URL,
  or when you want to read the full article from a search result.
- create_document: Create a downloadable document file. Use when the user asks you to generate,
  write, create, or export a file. Supported formats: .txt, .md, .csv, .pdf, .docx, .xlsx,
  .fdx (Final Draft screenplay). When the user says "Final Draft" they mean .fdx format.
  After creating a document, include the download link in your response using markdown:
  [Download filename](url)

When the user uploads a document and asks you to edit, revise, or modify it:
- For SMALL documents: you have the full content in context. Use create_document with the entire edited text.
- For LARGE documents (screenplays, long texts): you have a TABLE OF CONTENTS showing numbered sections.
  Tools available:
  * find_replace_document: For simple renames or word substitutions across the ENTIRE document (e.g.
    "change Ken to Ophelia"). One call handles everything. Use this first when the edit is a straightforward
    text replacement.
  * get_document_section + edit_document_section: For creative edits that require rewriting content.
    Read 4-5 sections, then edit ALL 4-5 of those sections before moving on. You MUST
    edit every section you read. Then continue to the next batch. Each edit accumulates
    into the same file. Do NOT stop between batches — continue until every relevant section
    is edited. Only show the download link after all edits are complete.
  * NEVER try to output the entire large document via create_document — it will fail."""

# Task-mode signals: keywords/patterns that indicate the user wants the LLM to use tools
_TASK_SIGNALS = [
    "search", "look up", "find", "google", "fetch", "read this",
    "create a", "write a", "generate a", "make a", "export",
    "document", "file", ".pdf", ".docx", ".txt", ".csv", ".xlsx", ".fdx",
    "edit the", "revise the", "modify the", "change the", "update the",
    "http://", "https://", "www.",
]


# ---------------------------------------------------------------------------
# Shared helpers for chat and streaming endpoints
# ---------------------------------------------------------------------------

def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


def _section_heading(uploaded_docs, section_index: int) -> str:
    """Look up the heading for a section index from uploaded docs."""
    for doc in uploaded_docs:
        if doc.sections_json and 0 <= section_index < len(doc.sections_json):
            return doc.sections_json[section_index].get("heading", "")
    return ""


async def _prepare_chat(
    user_id: uuid.UUID, body: ChatRequest, db: AsyncSession,
) -> dict:
    """Build conversation context, LLM messages, and call kwargs.

    Returns dict with keys: conversation, conv_id, messages, uploaded_docs,
    has_sectioned_docs, client, llm_kwargs.
    """
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
        title = body.message[:100].strip() or "New Chat"
        conversation = Conversation(user_id=user_id, title=title)
        db.add(conversation)
        await db.flush()
        conv_id = conversation.id

    # Retrieve relevant context from user's memory
    context = await retrieve_context(db, user_id, body.message)

    # Load per-user settings
    user_settings = await get_or_create_settings(db, user_id)
    # Determine mode: task (tools enabled) vs conversation (no tools)
    msg_lower = body.message.lower()
    has_docs = False  # will be set below after doc check
    is_task_mode = any(signal in msg_lower for signal in _TASK_SIGNALS)

    # Build messages for LLM
    messages: list[dict] = []
    if context:
        messages.append({
            "role": "system",
            "content": f"Relevant context from the user's memory:\n\n{context}",
        })

    # Load document metadata for this conversation
    doc_result = await db.execute(
        select(ConversationDocument)
        .where(
            ConversationDocument.conversation_id == conv_id,
            ConversationDocument.user_id == user_id,
        )
        .order_by(ConversationDocument.created_at)
    )
    uploaded_docs = doc_result.scalars().all()
    has_sectioned_docs = False
    if uploaded_docs:
        doc_parts = []
        for doc in uploaded_docs:
            if doc.sections_json:
                # Large document — inject TOC + relevant sections only
                has_sectioned_docs = True
                toc = build_table_of_contents(doc.sections_json)
                relevant = _find_relevant_sections(doc.sections_json, body.message)
                section_texts = []
                chars_used = 0
                for sect in relevant:
                    content = sect.get("content", "")
                    if chars_used + len(content) > 12000:
                        break
                    section_texts.append(
                        f"--- Section [{sect['index']}]: {sect['heading']} ---\n"
                        f"{content}\n"
                        f"--- end section [{sect['index']}] ---"
                    )
                    chars_used += len(content)
                doc_parts.append(
                    f"--- {doc.filename} (LARGE DOCUMENT — {len(doc.sections_json)} sections) ---\n"
                    f"{toc}\n\n"
                    + (
                        "RELEVANT SECTIONS (use get_document_section to read others):\n\n"
                        + "\n\n".join(section_texts)
                        if section_texts
                        else "Use get_document_section to read specific sections."
                    )
                    + f"\n--- end {doc.filename} ---"
                )
            else:
                # Small document — inject full content as before
                doc_parts.append(
                    f"--- {doc.filename} ---\n{doc.content}\n--- end {doc.filename} ---"
                )
        doc_context = (
            "The user has uploaded the following document(s) in this conversation. "
            + (
                "For large documents, use get_document_section and edit_document_section tools. "
                "Do NOT try to output the entire document via create_document.\n\n"
                if has_sectioned_docs
                else "You have the full content available and can edit it as requested.\n\n"
            )
            + "\n\n".join(doc_parts)
        )
        messages.append({"role": "system", "content": doc_context})
        is_task_mode = True  # documents always require tools

    # Select system prompt based on mode
    if is_task_mode:
        system_prompt = SYSTEM_PROMPT_TASK.format(agent_name=user_settings.agent_name)
    else:
        system_prompt = SYSTEM_PROMPT_CONVERSATION.format(agent_name=user_settings.agent_name)

    if user_settings.custom_system_prompt:
        system_prompt += f"\n\nAdditional instructions from the user:\n{user_settings.custom_system_prompt}"

    messages.insert(0, {"role": "system", "content": system_prompt})

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
        if token_count + msg_tokens > user_settings.history_token_budget:
            break
        token_count += msg_tokens
        selected.append(msg)
    selected.reverse()  # back to chronological order
    for msg in selected:
        messages.append({"role": msg.role, "content": msg.content})

    if conversation.summary:
        messages.append({
            "role": "system",
            "content": f"Conversation summary so far:\n{conversation.summary}",
        })

    messages.append({"role": "user", "content": body.message})

    # Build LLM call kwargs
    client = _get_llm_client()
    model = user_settings.llm_model
    _restricted = model.startswith("gpt-5") or model.startswith("o")

    llm_kwargs: dict = {
        "model": model,
        "messages": messages,
    }
    if is_task_mode:
        tools = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL, CREATE_DOCUMENT_TOOL]
        if has_sectioned_docs:
            tools.extend([EDIT_DOCUMENT_SECTION_TOOL, GET_DOCUMENT_SECTION_TOOL, FIND_REPLACE_DOCUMENT_TOOL])
        llm_kwargs["tools"] = tools
    # GPT-5 and o-series models only support default temperature
    if not _restricted:
        llm_kwargs["temperature"] = user_settings.llm_temperature
    # Determine output token budget.  When the conversation has uploaded
    # documents the LLM must be able to emit the full document inside a
    # create_document tool-call, so we compute a floor based on document size.
    # For sectioned docs, the LLM only edits one section at a time (~4K chars).
    effective_max_tokens = user_settings.llm_max_tokens
    if uploaded_docs:
        if has_sectioned_docs:
            # Sectioned: LLM emits one edited scene (~4K chars ~ 1200 tokens)
            # inside a tool call JSON wrapper, plus reasoning. 8192 gives headroom.
            doc_token_floor = 8192
        else:
            total_doc_chars = sum(len(d.content) for d in uploaded_docs)
            # ~3.5 chars per token for English text, plus headroom for JSON framing
            doc_token_floor = int(total_doc_chars / 3.5) + 512
        if effective_max_tokens is None or effective_max_tokens < doc_token_floor:
            effective_max_tokens = doc_token_floor

    # Hard cap to stay within model limits (gpt-4o max is 16384)
    if effective_max_tokens is not None:
        effective_max_tokens = min(effective_max_tokens, 16384)

    if effective_max_tokens is not None:
        if _restricted:
            llm_kwargs["max_completion_tokens"] = effective_max_tokens
        else:
            llm_kwargs["max_tokens"] = effective_max_tokens

    logger.info(
        "LLM call: model=%s, mode=%s, effective_max_tokens=%s, has_sectioned_docs=%s, num_tools=%d",
        model, "task" if is_task_mode else "conversation",
        effective_max_tokens, has_sectioned_docs, len(llm_kwargs.get("tools", [])),
    )

    return {
        "conversation": conversation,
        "conv_id": conv_id,
        "messages": messages,
        "uploaded_docs": uploaded_docs,
        "has_sectioned_docs": has_sectioned_docs,
        "client": client,
        "llm_kwargs": llm_kwargs,
        "history_tokens": token_count,
    }


async def _execute_tool_call(
    tool_call, uploaded_docs: list, user_id: uuid.UUID, db: AsyncSession,
) -> tuple[str, list[str]]:
    """Execute a single LLM tool call.

    Returns (result_text, progress_messages).
    """
    args = json.loads(tool_call.function.arguments)
    name = tool_call.function.name
    progress: list[str] = []

    if name == "web_search":
        query = args.get("query", "")
        logger.info(f"LLM invoked web_search for user {user_id}: {query!r}")
        progress.append(f"Searching: {query}")
        result = await web_search(query)

    elif name == "web_fetch":
        url = args.get("url", "")
        logger.info(f"LLM invoked web_fetch for user {user_id}: {url!r}")
        progress.append(f"Fetching: {url}")
        result = await web_fetch(url)

    elif name == "create_document":
        doc_filename = args.get("filename", "document.txt")
        doc_content = args.get("content", "")
        logger.info(f"LLM invoked create_document for user {user_id}: {doc_filename!r}")
        progress.append(f"Creating document: {doc_filename}")
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

    elif name == "get_document_section":
        sec_idx = args.get("section_index", 0)
        heading = _section_heading(uploaded_docs, sec_idx)
        logger.info(f"LLM invoked get_document_section for user {user_id}: section {sec_idx}")
        result = _handle_get_section(uploaded_docs, sec_idx)
        progress.append(f"Reading section {sec_idx}: {heading}")

    elif name == "edit_document_section":
        sec_idx = args.get("section_index", 0)
        heading = _section_heading(uploaded_docs, sec_idx)
        logger.info(f"LLM invoked edit_document_section for user {user_id}: section {sec_idx}")
        result = await _handle_edit_section(
            db, uploaded_docs, sec_idx, args.get("new_content", ""), user_id,
        )
        # Use updated heading after edit (sections may have been re-indexed)
        new_heading = _section_heading(uploaded_docs, sec_idx) or heading
        progress.append(f"Edited section {sec_idx}: {new_heading}")

    elif name == "find_replace_document":
        find_str = args.get("find", "")
        replace_str = args.get("replace", "")
        logger.info(f"LLM invoked find_replace_document for user {user_id}: {find_str!r} -> {replace_str!r}")
        result = await _handle_find_replace(
            db, uploaded_docs, find_str, replace_str, user_id,
        )
        progress.append(f"Replaced '{find_str}' with '{replace_str}'")

    else:
        result = f"Unknown tool: {name}"

    return result, progress


def _last_download_link(messages: list) -> str | None:
    """Scan tool results for the most recent download link."""
    for msg in reversed(messages):
        content = None
        if isinstance(msg, dict) and msg.get("role") == "tool":
            content = msg.get("content", "")
        if content:
            match = re.search(r"\[Download .+?\]\((/api/documents/download/[^)]+)\)", content)
            if match:
                return match.group(0)  # full markdown link
    return None


async def _finalize_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_message: str,
    assistant_content: str,
    conversation,
    conv_id: uuid.UUID,
    client: AsyncOpenAI,
):
    """Save messages and commit immediately. Embedding + summary run in background."""
    user_msg = Message(
        user_id=user_id, role="user", content=user_message,
        source=MessageSource.TEXT, conversation_id=conv_id,
    )
    assistant_msg = Message(
        user_id=user_id, role="assistant", content=assistant_content,
        source=MessageSource.TEXT, conversation_id=conv_id,
    )
    db.add(user_msg)
    db.add(assistant_msg)
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Fire embedding + summary as a background task (own DB session)
    asyncio.create_task(_background_embed_and_summarize(
        user_id, conv_id, user_message, assistant_content,
        conversation.summary, client,
    ))


async def _background_embed_and_summarize(
    user_id: uuid.UUID,
    conv_id: uuid.UUID,
    user_message: str,
    assistant_content: str,
    existing_summary: str | None,
    client: AsyncOpenAI,
):
    """Background: extract memories from the exchange and update conversation summary."""
    try:
        # Run memory extraction and summary generation concurrently
        (memories, mem_usage), (summary, sum_usage) = await asyncio.gather(
            _extract_memories(client, user_message, assistant_content),
            _generate_summary(client, user_message, assistant_content, existing_summary),
        )
        # Log token usage for both background LLM calls
        await _log_token_usage(user_id, SUMMARY_MODEL, mem_usage, "memory_extraction")
        await _log_token_usage(user_id, SUMMARY_MODEL, sum_usage, "summary")

        async with async_session_factory() as db:
            # Only embed if significant memories were extracted
            if memories:
                embeddings = await embed_texts(memories)
                for memory_text, embedding in zip(memories, embeddings):
                    db.add(MemoryEmbedding(
                        user_id=user_id, content=memory_text, embedding=embedding,
                    ))
                logger.info(
                    "Extracted %d memories from conv %s", len(memories), conv_id,
                )

            result = await db.execute(
                select(Conversation).where(Conversation.id == conv_id)
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.summary = summary
            await db.commit()

        # Flush accumulated embedding token usage
        await flush_embedding_tokens(user_id)
    except Exception as e:
        logger.error("Background embed/summarize failed for conv %s: %s", conv_id, e)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a text message and get a RAG-augmented LLM response."""
    ctx = await _prepare_chat(user_id, body, db)
    conversation = ctx["conversation"]
    conv_id = ctx["conv_id"]
    messages = ctx["messages"]
    uploaded_docs = ctx["uploaded_docs"]
    client = ctx["client"]
    llm_kwargs = ctx["llm_kwargs"]

    assistant_content = None
    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            completion = await client.chat.completions.create(**llm_kwargs)
        except Exception as e:
            logger.error("LLM API call failed on iteration %d: %s", iteration, e)
            break
        asyncio.create_task(_log_token_usage(user_id, llm_kwargs.get("model", ""), completion.usage, "chat"))
        choice = completion.choices[0]
        logger.info(
            "LLM iteration %d: finish_reason=%s, has_tool_calls=%s, has_content=%s, content_len=%s",
            iteration, choice.finish_reason,
            bool(choice.message.tool_calls),
            choice.message.content is not None,
            len(choice.message.content) if choice.message.content else 0,
        )

        if choice.finish_reason == "length":
            logger.warning("LLM output truncated (finish_reason=length) on iteration %d", iteration)
            assistant_content = choice.message.content
            break

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)
            for tool_call in choice.message.tool_calls:
                result, _ = await _execute_tool_call(
                    tool_call, uploaded_docs, user_id, db,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
        else:
            assistant_content = choice.message.content
            if assistant_content is None:
                logger.warning(
                    "LLM returned finish_reason=%s with no content on iteration %d",
                    choice.finish_reason, iteration,
                )
            break

    if assistant_content is None:
        logger.warning("Tool loop exhausted after %d iterations with no content", MAX_TOOL_ITERATIONS)
        download_link = _last_download_link(messages)
        if download_link:
            assistant_content = (
                "I ran into an issue and couldn't finish editing all sections, "
                "but here's the file with the edits completed so far:\n\n"
                f"{download_link}\n\n"
                "You can ask me to continue editing from where I left off."
            )
        else:
            assistant_content = "I'm sorry, I wasn't able to complete that request. Please try again."

    await _finalize_chat(
        db, user_id, body.message, assistant_content, conversation, conv_id, client,
    )

    return ChatResponse(response=assistant_content, conversation_id=str(conv_id))


async def _chat_stream(
    user_id: uuid.UUID, body: ChatRequest, db: AsyncSession,
):
    """Async generator yielding SSE events during the chat tool loop.

    Uses streaming LLM calls: content tokens are emitted immediately as
    {"type": "token"} events; tool-call argument fragments are buffered
    silently.  A final {"type": "content"} event carries the authoritative
    full text after streaming completes.
    """
    try:
        ctx = await _prepare_chat(user_id, body, db)
    except HTTPException as e:
        yield _sse_event({"type": "error", "message": e.detail})
        return

    conversation = ctx["conversation"]
    conv_id = ctx["conv_id"]
    messages = ctx["messages"]
    uploaded_docs = ctx["uploaded_docs"]
    client = ctx["client"]
    llm_kwargs = ctx["llm_kwargs"]
    history_tokens = ctx["history_tokens"]

    assistant_content = None
    for iteration in range(MAX_TOOL_ITERATIONS):
        # Enable streaming with usage reporting
        llm_kwargs["stream"] = True
        llm_kwargs["stream_options"] = {"include_usage": True}
        try:
            stream = await client.chat.completions.create(**llm_kwargs)
        except Exception as e:
            logger.error("LLM API call failed on iteration %d: %s", iteration, e)
            break

        accumulated_content = ""
        accumulated_tool_calls: dict[int, dict] = {}  # {index: {id, name, args}}
        finish_reason = None
        stream_usage = None

        async for chunk in stream:
            # Final chunk with usage has empty choices
            if hasattr(chunk, "usage") and chunk.usage is not None:
                stream_usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # Buffer tool-call argument fragments silently
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": tc.id or "",
                            "name": (tc.function.name if tc.function else "") or "",
                            "args": "",
                        }
                    else:
                        # Fill in id/name if they arrive in later chunks
                        if tc.id:
                            accumulated_tool_calls[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            accumulated_tool_calls[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        accumulated_tool_calls[idx]["args"] += tc.function.arguments

            # Stream content tokens to the client immediately
            if delta.content:
                accumulated_content += delta.content
                yield _sse_event({"type": "token", "text": delta.content})

        logger.info(
            "LLM iteration %d (streamed): finish_reason=%s, content_len=%d, tool_calls=%d",
            iteration, finish_reason, len(accumulated_content), len(accumulated_tool_calls),
        )
        asyncio.create_task(_log_token_usage(user_id, llm_kwargs.get("model", ""), stream_usage, "chat"))

        if finish_reason == "length":
            logger.warning("LLM output truncated (finish_reason=length) on iteration %d", iteration)
            assistant_content = accumulated_content
            break

        if finish_reason == "tool_calls" and accumulated_tool_calls:
            # Build a synthetic message object for the conversation history
            tool_calls_for_history = []
            for idx in sorted(accumulated_tool_calls.keys()):
                tc_data = accumulated_tool_calls[idx]
                tool_calls_for_history.append({
                    "id": tc_data["id"],
                    "type": "function",
                    "function": {
                        "name": tc_data["name"],
                        "arguments": tc_data["args"],
                    },
                })
            assistant_msg_for_history = {
                "role": "assistant",
                "content": accumulated_content or None,
                "tool_calls": tool_calls_for_history,
            }
            messages.append(assistant_msg_for_history)

            # Execute each tool call
            for tc_entry in tool_calls_for_history:
                # Create a lightweight object that _execute_tool_call can use
                class _ToolCall:
                    def __init__(self, entry):
                        self.id = entry["id"]
                        class _Fn:
                            def __init__(self, fn):
                                self.name = fn["name"]
                                self.arguments = fn["arguments"]
                        self.function = _Fn(entry["function"])
                tc_obj = _ToolCall(tc_entry)
                result, progress_msgs = await _execute_tool_call(
                    tc_obj, uploaded_docs, user_id, db,
                )
                for msg in progress_msgs:
                    yield _sse_event({"type": "progress", "message": msg})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_entry["id"],
                    "content": result,
                })
            # Continue the loop for the next LLM call
            # Reset stream flag (it gets set again at top of loop)
            continue
        else:
            # Normal stop — content is the final response
            assistant_content = accumulated_content if accumulated_content else None
            if assistant_content is None:
                logger.warning(
                    "LLM returned finish_reason=%s with no content on iteration %d",
                    finish_reason, iteration,
                )
            break

    if assistant_content is None:
        logger.warning("Tool loop exhausted after %d iterations with no content", MAX_TOOL_ITERATIONS)
        download_link = _last_download_link(messages)
        if download_link:
            assistant_content = (
                "I ran into an issue and couldn't finish editing all sections, "
                "but here's the file with the edits completed so far:\n\n"
                f"{download_link}\n\n"
                "You can ask me to continue editing from where I left off."
            )
        else:
            assistant_content = "I'm sorry, I wasn't able to complete that request. Please try again."

    try:
        await _finalize_chat(
            db, user_id, body.message, assistant_content, conversation, conv_id, client,
        )
    except Exception as e:
        logger.error("Failed to finalize streamed chat: %s", e)
        yield _sse_event({"type": "error", "message": "Failed to save conversation"})
        return

    yield _sse_event({"type": "content", "text": assistant_content})
    yield _sse_event({"type": "done", "conversation_id": str(conv_id), "history_tokens": history_tokens})


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a text message and stream progress + response as SSE events."""
    return StreamingResponse(
        _chat_stream(user_id, body, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


class EditMessageRequest(BaseModel):
    content: str


class RegenerateRequest(BaseModel):
    message_id: str


@router.put("/messages/{message_id}")
async def edit_message(
    message_id: uuid.UUID,
    body: EditMessageRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Edit a user message's content."""
    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.user_id == user_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "user":
        raise HTTPException(status_code=400, detail="Can only edit user messages")
    msg.content = body.content
    await db.commit()
    return {"ok": True}


@router.delete("/messages/{message_id}")
async def delete_message_and_after(
    message_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a message and all subsequent messages in the same conversation."""
    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.user_id == user_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.conversation_id:
        await db.execute(
            delete(Message).where(and_(
                Message.conversation_id == msg.conversation_id,
                Message.created_at >= msg.created_at,
                Message.user_id == user_id,
            ))
        )
    else:
        await db.execute(delete(Message).where(Message.id == message_id))
    await db.commit()
    return {"ok": True}


@router.post("/regenerate")
async def regenerate_message(
    body: RegenerateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete all messages after a user message and re-stream the response."""
    try:
        msg_id = uuid.UUID(body.message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message_id")

    result = await db.execute(
        select(Message).where(Message.id == msg_id, Message.user_id == user_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "user":
        raise HTTPException(status_code=400, detail="Can only regenerate from user messages")

    # Delete all messages after this one in the conversation
    if msg.conversation_id:
        await db.execute(
            delete(Message).where(and_(
                Message.conversation_id == msg.conversation_id,
                Message.created_at > msg.created_at,
                Message.user_id == user_id,
            ))
        )
        await db.commit()

    # Re-stream response for this message
    chat_body = ChatRequest(
        message=msg.content,
        conversation_id=str(msg.conversation_id) if msg.conversation_id else None,
    )

    # Delete the user message too — _finalize_chat will re-save it
    await db.execute(delete(Message).where(Message.id == msg_id))
    await db.commit()

    return StreamingResponse(
        _chat_stream(user_id, chat_body, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _find_relevant_sections(
    sections: list[dict], user_message: str,
) -> list[dict]:
    """Find sections relevant to the user's message via keyword matching.

    Returns matching sections ordered by relevance, plus positional matches
    for words like "opening", "ending", "first", "last".
    """
    if not sections:
        return []

    msg_lower = user_message.lower()
    words = set(msg_lower.split())

    scored: list[tuple[float, dict]] = []
    for sect in sections:
        heading_lower = sect.get("heading", "").lower()
        content_lower = sect.get("content", "").lower()
        score = 0.0

        # Keyword matching on heading (high weight)
        for word in words:
            if len(word) > 2 and word in heading_lower:
                score += 3.0

        # Keyword matching on content (lower weight)
        for word in words:
            if len(word) > 3 and word in content_lower:
                score += 0.5

        # Positional keywords
        idx = sect.get("index", 0)
        total = len(sections)
        if any(w in words for w in ("opening", "first", "beginning", "start")):
            if idx == 0:
                score += 5.0
        if any(w in words for w in ("ending", "last", "final", "end", "closing")):
            if idx == total - 1:
                score += 5.0

        # Scene number references like "scene 5"
        for w in ("scene", "section"):
            if w in msg_lower:
                pattern = rf"{w}\s+(\d+)"
                for m in re.finditer(pattern, msg_lower):
                    target_idx = int(m.group(1))
                    if idx == target_idx:
                        score += 10.0

        if score > 0:
            scored.append((score, sect))

    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored]


def _handle_get_section(
    uploaded_docs: list, section_index: int,
) -> str:
    """Handle the get_document_section tool call."""
    for doc in uploaded_docs:
        if doc.sections_json:
            sections = doc.sections_json
            if 0 <= section_index < len(sections):
                sect = sections[section_index]
                return (
                    f"Section [{section_index}]: {sect['heading']}\n\n"
                    f"{sect['content']}"
                )
            return f"Invalid section index {section_index}. Valid range: 0-{len(sections) - 1}"
    return "No sectioned document found in this conversation."


async def _handle_edit_section(
    db, uploaded_docs: list, section_index: int, new_content: str, user_id,
) -> str:
    """Handle the edit_document_section tool call.

    Surgically edits one section and re-indexes.  Dispatches by file format:
    FDX uses XML-level editing, TXT/MD uses paragraph splicing, DOCX/PDF
    uses extract→splice→edit_preserving_format.
    """
    for doc in uploaded_docs:
        if not doc.sections_json or not doc.original_bytes:
            continue

        ext = _get_extension(doc.filename)

        # --- Dispatch editing by format ---
        if ext == ".fdx":
            edited_bytes = edit_fdx_section(
                doc.original_bytes, doc.sections_json, section_index, new_content,
            )
            re_split_fn = split_fdx_into_scenes
        elif ext in (".txt", ".md"):
            edited_bytes = edit_text_section(
                doc.original_bytes, doc.sections_json, section_index, new_content,
            )
            re_split_fn = lambda b: split_large_text(b.decode("utf-8", errors="replace"))
        elif ext == ".docx":
            edited_bytes = edit_docx_section(
                doc.original_bytes, doc.sections_json, section_index, new_content,
            )
            re_split_fn = lambda b: split_large_text(extract_text_sync(doc.filename, b))
        elif ext == ".pdf":
            edited_bytes = edit_rich_section(
                doc.original_bytes, doc.filename, doc.sections_json,
                section_index, new_content, extract_text_sync,
            )
            re_split_fn = lambda b: split_large_text(extract_text_sync(doc.filename, b))
        else:
            return f"Unsupported format for section editing: {ext}"

        if edited_bytes is None:
            return f"Failed to edit section {section_index}. Check the section index and try again."

        # Re-index sections from the edited bytes
        new_sections = re_split_fn(edited_bytes)

        # Update the ConversationDocument in-place so subsequent edits
        # in the same request use the updated bytes and ranges
        doc.original_bytes = edited_bytes
        doc.sections_json = new_sections

        # Also update extracted text content
        from document.parser import extract_text as _extract
        try:
            doc.content = await _extract(doc.filename, edited_bytes)
        except Exception:
            pass  # non-critical; original_bytes is the source of truth

        # Store for download
        doc_id = store_document(user_id, doc.filename, edited_bytes)
        download_url = f"/api/documents/download/{doc_id}"

        sect_heading = ""
        if 0 <= section_index < len(doc.sections_json):
            sect_heading = doc.sections_json[section_index].get("heading", "")

        return (
            f"Section [{section_index}] ({sect_heading}) edited successfully. "
            f"All edits are accumulated in the same file. "
            f"If you have MORE sections to edit, do those next BEFORE showing a download link. "
            f"Only after ALL edits are done, include this exact markdown link in your final response:\n"
            f"[Download {doc.filename}]({download_url})"
        )

    return "No sectioned document found in this conversation."


async def _handle_find_replace(
    db, uploaded_docs: list, find: str, replace: str, user_id,
) -> str:
    """Handle the find_replace_document tool call.

    Dispatches by file format: FDX uses XML-level replacement, TXT/MD uses
    regex on decoded text, DOCX/PDF uses extract→replace→edit_preserving_format.
    """
    for doc in uploaded_docs:
        if not doc.original_bytes:
            continue

        ext = _get_extension(doc.filename)

        # --- Dispatch find-replace by format ---
        if ext == ".fdx":
            result = find_replace_fdx(doc.original_bytes, find, replace)
            re_split_fn = split_fdx_into_scenes
        elif ext in (".txt", ".md"):
            result = find_replace_text(doc.original_bytes, find, replace)
            re_split_fn = lambda b: split_large_text(b.decode("utf-8", errors="replace"))
        elif ext == ".docx":
            result = find_replace_docx(doc.original_bytes, find, replace)
            re_split_fn = lambda b: split_large_text(extract_text_sync(doc.filename, b))
        elif ext == ".pdf":
            result = find_replace_rich(
                doc.original_bytes, doc.filename, find, replace,
                extract_fn=extract_text_sync,
            )
            re_split_fn = lambda b: split_large_text(extract_text_sync(doc.filename, b))
        else:
            return f"Unsupported format for find-and-replace: {ext}"

        if result is None:
            return f"No occurrences of {find!r} found in the document."

        edited_bytes, count = result

        # Re-index sections and update the document record
        if doc.sections_json:
            doc.sections_json = re_split_fn(edited_bytes)
        doc.original_bytes = edited_bytes

        from document.parser import extract_text as _extract
        try:
            doc.content = await _extract(doc.filename, edited_bytes)
        except Exception:
            pass

        doc_id = store_document(user_id, doc.filename, edited_bytes)
        download_url = f"/api/documents/download/{doc_id}"

        return (
            f"Replaced {count} occurrence(s) of {find!r} with {replace!r} throughout the document. "
            f"Include this exact markdown link in your response:\n"
            f"[Download {doc.filename}]({download_url})"
        )

    return "No document with original bytes found in this conversation."


def _get_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot."""
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()
