"""Voice tool callback endpoints.

These endpoints are called by Omnia when its LLM invokes a tool during a voice session.
Authentication is via voice session token (not JWT), since Omnia is the caller.

POST /api/voice-tools/rag-query    — Search user's knowledge base
POST /api/voice-tools/store-memory — Store new information
POST /api/voice-tools/web-search   — Search the internet
"""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from memory.embeddings import embed_text
from memory.rag import retrieve_context
from memory.vector_store import store_embedding
from models import get_db
from search.google_search import web_search
from search.web_fetch import web_fetch
from voice.session_manager import validate_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice-tools", tags=["voice-tools"])


async def _get_user_id_from_session(request: Request) -> uuid.UUID:
    """Extract and validate voice session token from Authorization header.

    The session token is the authoritative source for user_id.
    We ignore any user_id in the request body — Redis lookup is authoritative.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = auth_header[7:]
    try:
        return await validate_session(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired voice session token",
        )


class RagQueryRequest(BaseModel):
    query: str
    user_id: str | None = None  # Ignored — session token is authoritative
    call_id: str | None = None


class RagQueryResponse(BaseModel):
    result: str


class StoreMemoryRequest(BaseModel):
    content: str
    user_id: str | None = None  # Ignored — session token is authoritative
    call_id: str | None = None


class StoreMemoryResponse(BaseModel):
    status: str


class WebSearchRequest(BaseModel):
    query: str
    user_id: str | None = None  # Ignored — session token is authoritative
    call_id: str | None = None


class WebSearchResponse(BaseModel):
    result: str


class WebFetchRequest(BaseModel):
    url: str
    user_id: str | None = None  # Ignored — session token is authoritative
    call_id: str | None = None


class WebFetchResponse(BaseModel):
    result: str


@router.post("/rag-query", response_model=RagQueryResponse)
async def rag_query(
    body: RagQueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Search the user's knowledge base.

    Called by Omnia when its LLM invokes the rag_query tool.
    Returns relevant context from the user's stored memories.
    """
    user_id = await _get_user_id_from_session(request)
    logger.info(f"RAG query for user {user_id}: {body.query[:100]}")

    context = await retrieve_context(db, user_id, body.query)
    if not context:
        return RagQueryResponse(result="No relevant information found in the user's knowledge base.")

    return RagQueryResponse(result=context)


@router.post("/store-memory", response_model=StoreMemoryResponse)
async def store_memory(
    body: StoreMemoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Store new information in the user's knowledge base.

    Called by Omnia when its LLM invokes the store_memory tool.
    Embeds the content and stores it in pgvector for future retrieval.
    """
    user_id = await _get_user_id_from_session(request)
    logger.info(f"Storing memory for user {user_id}: {body.content[:100]}")

    embedding = await embed_text(body.content)
    await store_embedding(db, user_id, body.content, embedding)
    await db.commit()

    return StoreMemoryResponse(status="stored")


@router.post("/web-search", response_model=WebSearchResponse)
async def voice_web_search(
    body: WebSearchRequest,
    request: Request,
):
    """Search the internet for current information.

    Called by Omnia when its LLM invokes the web_search tool.
    Returns formatted search results from Google Custom Search.
    """
    user_id = await _get_user_id_from_session(request)
    logger.info(f"Voice web search for user {user_id}: {body.query[:100]}")

    result = await web_search(body.query)
    return WebSearchResponse(result=result)


@router.post("/web-fetch", response_model=WebFetchResponse)
async def voice_web_fetch(
    body: WebFetchRequest,
    request: Request,
):
    """Fetch and read the content of a web page.

    Called by Omnia when its LLM invokes the web_fetch tool.
    Returns extracted text content from the URL.
    """
    user_id = await _get_user_id_from_session(request)
    logger.info(f"Voice web fetch for user {user_id}: {body.url[:100]}")

    result = await web_fetch(body.url)
    return WebFetchResponse(result=result)
