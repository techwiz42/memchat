"""Memchat FastAPI application."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.base import Base, async_engine
from api import auth, chat, documents, settings, voice, voice_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Memchat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(settings.router)
app.include_router(voice.router)
app.include_router(voice_tools.router)


@app.on_event("startup")
async def startup():
    """Create database tables and start background workers."""
    logger.info("Creating database tables...")
    async with async_engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready.")

    # Start background summarizer
    from workers.summarizer import start_summarizer
    start_summarizer()
    logger.info("Background summarizer started.")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
