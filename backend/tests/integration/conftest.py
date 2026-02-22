"""Integration-test fixtures that need PostgreSQL + pgvector.

Auto-skips if the ``memchat_test`` database is unreachable.
"""

import os
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from models.base import Base


_PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://memchat:testpassword@localhost:5432/memchat_test",
)

_pg_engine = create_async_engine(_PG_URL, echo=False)
_PgSession = async_sessionmaker(_pg_engine, class_=AsyncSession, expire_on_commit=False)


async def _pg_available() -> bool:
    try:
        async with _pg_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True, scope="module")
async def _require_pg():
    if not await _pg_available():
        pytest.skip("PostgreSQL + pgvector not available (memchat_test)")


@pytest.fixture(autouse=True)
async def _pg_tables():
    """Create pgvector extension + all tables, then drop after test."""
    async with _pg_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def pg_session():
    """Yield a real PostgreSQL session."""
    async with _PgSession() as session:
        yield session
