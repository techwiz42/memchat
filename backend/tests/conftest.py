"""Master test fixtures.

Environment variables are set BEFORE any application imports so that
``config.Settings()`` initialises with test-safe values and never
touches Docker secrets or a production database.
"""

import os, uuid

# ── Set test env vars before any app import ──────────────────────────
os.environ.update({
    "DATABASE_URL": "sqlite+aiosqlite://",
    "REDIS_URL": "redis://localhost:6379/0",
    "POSTGRES_PASSWORD": "testpassword",
    "OMNIA_API_KEY": "test-omnia-key",
    "LLM_API_KEY": "test-llm-key",
    "EMBEDDING_API_KEY": "test-embedding-key",
    "APP_SECRET_KEY": "test-secret-key-for-jwt-signing",
    "PUBLIC_BASE_URL": "https://test.example.com",
})

import pytest
import fakeredis.aioredis as fakeredis_aio

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Now safe to import application code
from models.base import Base, get_db
from models.user import User
from models.conversation import Message
from models.voice_session import VoiceSession
from auth.jwt import create_access_token


# ── SQLite async engine (skip MemoryEmbedding – needs pgvector) ──────
_test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
_TestSession = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

# Tables safe for SQLite (no Vector columns)
_SQLITE_TABLES = [
    User.__table__,
    Message.__table__,
    VoiceSession.__table__,
]


@pytest.fixture(autouse=True)
async def _create_tables():
    """Create and drop SQLite tables around every test."""
    async with _test_engine.begin() as conn:
        for table in _SQLITE_TABLES:
            await conn.run_sync(table.create, checkfirst=True)
    yield
    async with _test_engine.begin() as conn:
        for table in reversed(_SQLITE_TABLES):
            await conn.run_sync(table.drop, checkfirst=True)


@pytest.fixture
async def db_session():
    """Yield a test DB session with auto-rollback."""
    async with _TestSession() as session:
        yield session


@pytest.fixture
async def test_client(db_session: AsyncSession):
    """HTTPX async client wired to the FastAPI app, with DB override.

    The startup event is NOT run (no ``CREATE EXTENSION vector`` on SQLite).
    """
    from main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace session_manager._get_redis with a fakeredis instance."""
    server = fakeredis_aio.FakeServer()
    fr = fakeredis_aio.FakeRedis(server=server, decode_responses=True)
    import voice.session_manager as sm
    monkeypatch.setattr(sm, "_get_redis", lambda: fr)
    return fr


@pytest.fixture
async def registered_user(db_session: AsyncSession) -> dict:
    """Insert a user and return ``{id, email, access_token}``."""
    from passlib.hash import bcrypt

    user_id = uuid.uuid4()
    user = User(id=user_id, email="test@example.com", hashed_password=bcrypt.hash("password123"))
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user_id)
    return {"id": user_id, "email": "test@example.com", "access_token": token}


@pytest.fixture
def auth_headers(registered_user: dict) -> dict[str, str]:
    """Authorization header for the registered test user."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}
