"""Memchat FastAPI application."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.base import Base, async_engine
from api import auth, chat, conversations, documents, settings, voice, voice_tools, vision_ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Memchat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://memchat.cyberiad.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(documents.router)
app.include_router(settings.router)
app.include_router(voice.router)
app.include_router(voice_tools.router)
app.include_router(vision_ws.router)


@app.on_event("startup")
async def startup():
    """Create database tables and start background workers."""
    logger.info("Creating database tables...")
    async with async_engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        # Migrate: add 'vision' to messagesource enum if not present
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TYPE messagesource ADD VALUE IF NOT EXISTS 'vision'"
            )
        )
        await conn.run_sync(Base.metadata.create_all)
        # Migrate: add agent_name column if it doesn't exist
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS agent_name VARCHAR(100) DEFAULT 'Assistant'"
            )
        )
        # Migrate: add conversation_id column to messages if it doesn't exist
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id)"
            )
        )
    logger.info("Database tables ready.")

    # Start background summarizer
    from workers.summarizer import start_summarizer
    start_summarizer()
    logger.info("Background summarizer started.")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
