"""Document upload endpoint — extract, chunk, and embed into memory."""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import select
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from config import settings
from document.parser import extract_text, ALLOWED_EXTENSIONS, IMAGE_EXTENSIONS
from document.store import get_document, store_document
from document.vision import analyze_image
from document.chunker import chunk_text
from memory.embeddings import embed_text
from memory.vector_store import store_embedding
from models import Conversation, ConversationDocument, Message, MessageSource, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class UploadResponse(BaseModel):
    response: str
    filename: str
    chunks: int
    extracted_text: str
    conversation_id: str | None = None
    download_url: str | None = None


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    message: str = Form(""),
    conversation_id: str | None = Form(None),
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

    # Extract text (or analyze image)
    try:
        if ext in IMAGE_EXTENSIONS:
            extracted = await analyze_image(filename, content, settings.llm_api_key)
        else:
            extracted = await extract_text(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not extracted.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract any text from the uploaded file.",
        )

    # Store the original file for later download
    doc_id = store_document(user_id, filename, content)
    download_url = f"/api/documents/download/{doc_id}"

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

    # Resolve conversation — auto-create if none provided
    conv_id: uuid.UUID | None = None
    if conversation_id:
        try:
            conv_id = uuid.UUID(conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation_id")
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == user_id
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation:
            conversation.updated_at = datetime.now(timezone.utc)
    else:
        # Auto-create a conversation so the full document is scoped to it
        conversation = Conversation(
            user_id=user_id,
            title=f"Document: {filename[:80]}",
        )
        db.add(conversation)
        await db.flush()
        conv_id = conversation.id

    # Store full document text + original bytes scoped to this conversation
    if conv_id is not None:
        doc_record = ConversationDocument(
            user_id=user_id,
            conversation_id=conv_id,
            filename=filename,
            content=extracted,
            original_bytes=content,
        )
        db.add(doc_record)

    # Store a user message recording the upload
    upload_note = f"[Uploaded document: {filename}]"
    user_msg = Message(
        user_id=user_id,
        role="user",
        content=upload_note,
        source=MessageSource.TEXT,
        conversation_id=conv_id,
    )
    db.add(user_msg)

    # Build confirmation response
    confirmation = (
        f"I've processed your document **{filename}** and added it to your knowledge base. "
        f"It was split into {len(chunks)} chunk{'s' if len(chunks) != 1 else ''} "
        f"for retrieval. You can ask me questions about its content, or ask me to "
        f"edit/revise it and I'll provide the updated document as a download."
    )

    assistant_msg = Message(
        user_id=user_id,
        role="assistant",
        content=confirmation,
        source=MessageSource.TEXT,
        conversation_id=conv_id,
    )
    db.add(assistant_msg)

    await db.commit()

    return UploadResponse(
        response=confirmation,
        filename=filename,
        chunks=len(chunks),
        extracted_text=extracted,
        conversation_id=str(conv_id) if conv_id else None,
        download_url=download_url,
    )


CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".fdx": "application/xml",
}


@router.get("/download/{doc_id}")
async def download_document(
    doc_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Download a generated document by its ID."""
    result = get_document(doc_id, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found or expired")

    filename, data = result
    ext = _get_extension(filename)
    content_type = CONTENT_TYPES.get(ext, "application/octet-stream")

    return Response(
        content=bytes(data),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot."""
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()
