"""WebSocket endpoint for live camera vision with YOLO change detection.

Protocol:
  Client → Server: binary JPEG frames, or JSON {"type": "stop"}
  Server → Client:
    {"type": "detection", "objects": {"person": 2}, "frame": 42}
    {"type": "analysis", "content": "...", "trigger": "new_objects: {dog}"}
    {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
import uuid

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth.jwt import ALGORITHM
from config import settings
from document.vision import analyze_image
from memory.embeddings import embed_text
from memory.vector_store import MemoryEmbedding
from models import Message, MessageSource
from models.base import async_session_factory
from vision.change_detector import (
    ChangeDetectorState,
    build_snapshot,
    should_invoke_llm,
)
from vision.detector import detect_objects

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vision"])


def _authenticate_ws(token: str) -> uuid.UUID:
    """Validate JWT from WebSocket query param. Returns user_id.

    WebSocket handshakes cannot carry Authorization headers,
    so the token is passed as ?token=... query parameter.
    We decode manually instead of using decode_token() which
    raises HTTPException (inappropriate for WebSocket context).
    """
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")

    if payload.get("type") != "access":
        raise ValueError("Invalid token type")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise ValueError("Invalid token payload")


async def _analyze_and_send(
    ws: WebSocket,
    user_id: uuid.UUID,
    frame_bytes: bytes,
    trigger: str,
) -> None:
    """Run OpenAI Vision analysis and send result over WebSocket.

    Runs as a detached asyncio task. Uses its own DB session since
    it outlives the frame processing loop iteration.
    """
    try:
        # Call existing vision analysis
        analysis = await analyze_image("camera_frame.jpg", frame_bytes, settings.llm_api_key)

        # Send analysis to client
        await ws.send_json({
            "type": "analysis",
            "content": analysis,
            "trigger": trigger,
        })

        # Store as VISION message and embed for RAG
        async with async_session_factory() as db:
            msg = Message(
                user_id=user_id,
                role="assistant",
                content=analysis,
                source=MessageSource.VISION,
            )
            db.add(msg)

            await db.commit()

        # Embed vision analysis in background (don't block the websocket)
        asyncio.create_task(_background_embed_vision(user_id, analysis))

    except WebSocketDisconnect:
        pass  # Client disconnected while we were analyzing
    except Exception:
        logger.exception("Vision analysis failed")
        try:
            await ws.send_json({"type": "error", "message": "Vision analysis failed"})
        except Exception:
            pass


async def _background_embed_vision(user_id: uuid.UUID, analysis: str):
    """Background: embed vision analysis into RAG memory."""
    try:
        content = f"[Vision analysis] {analysis}"
        embedding = await embed_text(content)
        async with async_session_factory() as db:
            db.add(MemoryEmbedding(user_id=user_id, content=content, embedding=embedding))
            await db.commit()
    except Exception as e:
        logger.error("Background vision embedding failed for user %s: %s", user_id, e)


@router.websocket("/api/vision/stream")
async def vision_stream(ws: WebSocket):
    """WebSocket endpoint for live camera frame processing."""
    # Authenticate via query param
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    try:
        user_id = _authenticate_ws(token)
    except ValueError as e:
        await ws.close(code=4001, reason=str(e))
        return

    await ws.accept()
    logger.info("Vision WebSocket connected for user %s", user_id)

    state = ChangeDetectorState()
    frame_count = 0
    loop = asyncio.get_event_loop()

    try:
        while True:
            data = await ws.receive()

            # Handle JSON control messages
            if "text" in data:
                try:
                    msg = json.loads(data["text"])
                    if msg.get("type") == "stop":
                        break
                except (json.JSONDecodeError, TypeError):
                    pass
                continue

            # Handle binary JPEG frames
            if "bytes" not in data:
                continue

            frame_bytes = data["bytes"]
            frame_count += 1

            # Run YOLO detection in thread pool (synchronous, ~20-50ms)
            detections = await loop.run_in_executor(None, detect_objects, frame_bytes)

            # Build snapshot and send detection summary
            snapshot = build_snapshot(detections)
            await ws.send_json({
                "type": "detection",
                "objects": dict(snapshot),
                "frame": frame_count,
            })

            # Check if scene changed enough to warrant LLM analysis
            should_call, trigger = should_invoke_llm(snapshot, state)
            if should_call:
                # Fire-and-forget: don't block frame processing
                asyncio.create_task(
                    _analyze_and_send(ws, user_id, frame_bytes, trigger)
                )

    except WebSocketDisconnect:
        logger.info("Vision WebSocket disconnected for user %s", user_id)
    except Exception:
        logger.exception("Vision WebSocket error for user %s", user_id)
    finally:
        logger.info("Vision WebSocket closed for user %s (frames: %d)", user_id, frame_count)
