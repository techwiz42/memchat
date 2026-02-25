"""Text chat endpoint with RAG-augmented LLM responses and web search tool."""

import json
import re
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
from document.editor import edit_preserving_format, edit_fdx_section
from document.generator import generate_document
from document.scene_splitter import split_fdx_into_scenes, split_large_text, build_table_of_contents
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

MAX_TOOL_ITERATIONS = 8

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

When the user uploads a document and asks you to edit, revise, or modify it:
- For SMALL documents: you have the full content in context. Use create_document with the entire edited text.
- For LARGE documents (screenplays, long texts): you have a TABLE OF CONTENTS showing numbered sections.
  Use get_document_section to read a section, then edit_document_section to edit it.
  Each edit_document_section call surgically updates just that section in the original file.
  You can make multiple section edits in sequence. After editing, a download link is provided automatically.
  NEVER try to output the entire large document via create_document — it will fail.

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

    tools = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL, CREATE_DOCUMENT_TOOL]
    if has_sectioned_docs:
        tools.extend([EDIT_DOCUMENT_SECTION_TOOL, GET_DOCUMENT_SECTION_TOOL])
    llm_kwargs: dict = {
        "model": model,
        "messages": messages,
        "tools": tools,
    }
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
            # Sectioned: LLM emits one edited scene (~4K chars ≈ 1200 tokens)
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
        "LLM call: model=%s, effective_max_tokens=%s, has_sectioned_docs=%s, num_tools=%d",
        model, effective_max_tokens, has_sectioned_docs, len(tools),
    )

    assistant_content = None
    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            completion = await client.chat.completions.create(**llm_kwargs)
        except Exception as e:
            logger.error("LLM API call failed on iteration %d: %s", iteration, e)
            break
        choice = completion.choices[0]
        logger.info(
            "LLM iteration %d: finish_reason=%s, has_tool_calls=%s, has_content=%s, content_len=%s",
            iteration, choice.finish_reason,
            bool(choice.message.tool_calls),
            choice.message.content is not None,
            len(choice.message.content) if choice.message.content else 0,
        )

        if choice.finish_reason == "length":
            # Output was truncated — tool call or content is incomplete.
            # If the LLM was trying to generate a tool call, the JSON is
            # likely malformed.  Break out and return whatever content exists.
            logger.warning("LLM output truncated (finish_reason=length) on iteration %d", iteration)
            assistant_content = choice.message.content
            break

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
                elif tool_call.function.name == "get_document_section":
                    sec_idx = args.get("section_index", 0)
                    logger.info(f"LLM invoked get_document_section for user {user_id}: section {sec_idx}")
                    result = _handle_get_section(uploaded_docs, sec_idx)
                elif tool_call.function.name == "edit_document_section":
                    sec_idx = args.get("section_index", 0)
                    new_sec_content = args.get("new_content", "")
                    logger.info(f"LLM invoked edit_document_section for user {user_id}: section {sec_idx}")
                    result = await _handle_edit_section(
                        db, uploaded_docs, sec_idx, new_sec_content, user_id,
                    )
                else:
                    result = f"Unknown tool: {tool_call.function.name}"
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

    Surgically edits one section of the FDX, re-indexes sections, stores the
    updated bytes, and returns a download link.
    """
    for doc in uploaded_docs:
        if not doc.sections_json or not doc.original_bytes:
            continue

        ext = _get_extension(doc.filename)
        if ext == ".fdx":
            edited_bytes = edit_fdx_section(
                doc.original_bytes, doc.sections_json, section_index, new_content,
            )
            if edited_bytes is None:
                return f"Failed to edit section {section_index}. Check the section index and try again."

            # Re-index sections from the edited bytes
            new_sections = split_fdx_into_scenes(edited_bytes)

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
        else:
            return f"Section editing is currently supported for FDX files only. Use create_document for {ext} files."

    return "No sectioned document found in this conversation."


def _get_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot."""
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()
