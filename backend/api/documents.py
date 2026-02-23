"""Document upload endpoint — extract, chunk, and embed into memory."""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from document.parser import extract_text, ALLOWED_EXTENSIONS
from document.chunker import chunk_text
from memory.embeddings import embed_text
from memory.vector_store import store_embedding
from models import Message, MessageSource, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class UploadResponse(BaseModel):
    response: str
    filename: str
    chunks: int


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    message: str = Form(""),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document, extract text, chunk it, and embed into memory."""
    filename = file.filename or "unknown"

    # Validate extension
    ext = _get_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    # Extract text
    try:
        extracted = await extract_text(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not extracted.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract any text from the uploaded file.",
        )

    # Chunk the text
    chunks = chunk_text(extracted)
    logger.info(
        "Document '%s' for user %s: extracted %d chars, %d chunks",
        filename,
        user_id,
        len(extracted),
        len(chunks),
    )

    # Embed and store each chunk
    for i, chunk in enumerate(chunks):
        chunk_label = f"[Document: {filename} | chunk {i + 1}/{len(chunks)}]\n{chunk}"
        embedding = await embed_text(chunk_label)
        await store_embedding(db, user_id, chunk_label, embedding)

    # Store a user message recording the upload
    upload_note = f"[Uploaded document: {filename}]"
    user_msg = Message(
        user_id=user_id,
        role="user",
        content=upload_note,
        source=MessageSource.TEXT,
    )
    db.add(user_msg)

    # Build confirmation response
    confirmation = (
        f"I've processed your document **{filename}** and added it to your knowledge base. "
        f"It was split into {len(chunks)} chunk{'s' if len(chunks) != 1 else ''} "
        f"for retrieval. You can now ask me questions about its content."
    )

    assistant_msg = Message(
        user_id=user_id,
        role="assistant",
        content=confirmation,
        source=MessageSource.TEXT,
    )
    db.add(assistant_msg)

    await db.commit()

    return UploadResponse(
        response=confirmation,
        filename=filename,
        chunks=len(chunks),
    )


def _get_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot."""
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()
