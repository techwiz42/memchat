"""Voice session API endpoints.

POST /api/voice/start  — Create Omnia call, return joinUrl for browser WebRTC
POST /api/voice/end    — End session, store transcript
GET  /api/voice/voices — List available Omnia voices
"""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from config import settings
from memory.embeddings import embed_text
from memory.vector_store import store_embedding
from models import VoiceSession, VoiceSessionStatus, Message, MessageSource, get_db
from api.settings import get_or_create_settings
from voice.omnia_client import OmniaVoiceClient, OmniaAPIError
from voice.omnia_config import build_inline_call_config
from voice.session_manager import create_session, end_session, end_session_by_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class StartVoiceResponse(BaseModel):
    call_id: str
    join_url: str


class EndVoiceRequest(BaseModel):
    call_id: str
    client_transcript: str | None = None


class EndVoiceResponse(BaseModel):
    transcript: str | None
    summary: str | None


@router.post("/start", response_model=StartVoiceResponse)
async def start_voice_session(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Start a voice session.

    Creates a voice session token, builds the Omnia inline call config,
    and returns the joinUrl for the browser to connect via WebRTC.
    """
    # Fetch recent conversation history for continuity
    recent = await db.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_messages = list(reversed(recent.scalars().all()))

    # Load per-user voice settings
    user_settings = await get_or_create_settings(db, user_id)

    # Create session token for tool callback auth
    session_token = await create_session(user_id)

    # Build inline call config with recent context and per-user voice/language
    call_config = build_inline_call_config(
        session_token,
        str(user_id),
        recent_messages,
        agent_name=user_settings.agent_name,
        voice_name=user_settings.omnia_voice_name,
        language_code=user_settings.omnia_language_code,
    )

    # Create call via Omnia API
    client = OmniaVoiceClient(api_key=settings.omnia_api_key)
    try:
        result = await client.create_inline_call(call_config)
    except OmniaAPIError as e:
        logger.error(f"Failed to create Omnia call: {e}")
        await end_session(session_token)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Omnia API error: {e.message}")

    call_id = result.get("callId") or result.get("call_id") or result.get("id")
    join_url = result.get("joinUrl") or result.get("join_url") or result.get("websocketUrl")

    if not call_id or not join_url:
        logger.error(f"Unexpected Omnia response: {result}")
        await end_session(session_token)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Omnia API returned unexpected response format",
        )

    # Track the voice session
    voice_session = VoiceSession(user_id=user_id, omnia_call_id=call_id)
    db.add(voice_session)
    await db.commit()

    return StartVoiceResponse(call_id=call_id, join_url=join_url)


@router.post("/end", response_model=EndVoiceResponse)
async def end_voice_session(
    body: EndVoiceRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """End a voice session and store the transcript.

    Fetches call details from Omnia, stores transcript in conversation history,
    and ends the voice session token.
    """
    # Find the voice session
    result = await db.execute(
        select(VoiceSession).where(
            VoiceSession.omnia_call_id == body.call_id,
            VoiceSession.user_id == user_id,
        )
    )
    voice_session = result.scalar_one_or_none()
    if not voice_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice session not found")

    # Fetch call details from Omnia
    client = OmniaVoiceClient(api_key=settings.omnia_api_key)
    try:
        call_data = await client.get_call(body.call_id)
    except OmniaAPIError as e:
        logger.error(f"Failed to get Omnia call details: {e}")
        call_data = {}

    transcript = call_data.get("transcript")
    summary = call_data.get("summary")

    # Fall back to client-captured transcript if Omnia didn't return one
    if not transcript and body.client_transcript:
        logger.info("Using client-provided transcript (Omnia returned none)")
        transcript = body.client_transcript

    # Update voice session record
    voice_session.status = VoiceSessionStatus.ENDED
    voice_session.transcript = transcript
    voice_session.summary = summary
    voice_session.ended_at = datetime.now(timezone.utc)

    # Store transcript as conversation message and embed into RAG
    if transcript:
        transcript_content = f"[Voice conversation transcript]\n{transcript}"
        msg = Message(
            user_id=user_id,
            role="assistant",
            content=transcript_content,
            source=MessageSource.VOICE,
        )
        db.add(msg)

        # Embed voice transcript so it's findable via RAG in future text/voice sessions
        embedding = await embed_text(transcript_content)
        await store_embedding(db, user_id, transcript_content, embedding)

    await db.commit()

    # End the Redis session token for this user
    await end_session_by_user(user_id)

    return EndVoiceResponse(transcript=transcript, summary=summary)


@router.get("/voices")
async def list_voices(user_id: uuid.UUID = Depends(get_current_user_id)):
    """List available Omnia TTS voices."""
    client = OmniaVoiceClient(api_key=settings.omnia_api_key)
    try:
        voices = await client.list_voices()
        return {"voices": voices}
    except OmniaAPIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Omnia API error: {e.message}")
