"""Memchat FastAPI application."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.base import Base, async_engine
from api import admin, auth, chat, conversations, documents, settings, voice, voice_tools, vision_ws, memory, document_library

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

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(documents.router)
app.include_router(settings.router)
app.include_router(voice.router)
app.include_router(voice_tools.router)
app.include_router(vision_ws.router)
app.include_router(memory.router)
app.include_router(document_library.router)


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
        # Migrate: add custom_system_prompt column if it doesn't exist
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS custom_system_prompt TEXT DEFAULT ''"
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
        # GIN index for full-text search on message content
        await conn.execute(
            __import__("sqlalchemy").text(
                "CREATE INDEX IF NOT EXISTS ix_messages_content_tsvector "
                "ON messages USING GIN (to_tsvector('english', content))"
            )
        )
        # HNSW index for fast approximate nearest-neighbor vector search
        await conn.execute(
            __import__("sqlalchemy").text(
                "CREATE INDEX IF NOT EXISTS ix_memory_embeddings_hnsw "
                "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
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
