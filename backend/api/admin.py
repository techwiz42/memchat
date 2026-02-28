"""Admin dashboard API — restricted to ADMIN_EMAILS."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import BigInteger, column, func, not_, or_, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from memory.vector_store import MemoryEmbedding
from models import (
    Conversation,
    Message,
    MessageSource,
    TokenUsage,
    User,
    VoiceSession,
    get_db,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_EMAILS = {"pete@cyberiad.ai"}
EXCLUDED_DOMAINS = ("@test.com", "@example.com")


async def require_admin(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Raise 403 unless the caller's email is in ADMIN_EMAILS."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user_id


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SourceBreakdown(BaseModel):
    text: int
    voice: int
    vision: int


class DayCount(BaseModel):
    date: str
    count: int


class UserStats(BaseModel):
    email: str
    display_name: str | None
    joined: str
    messages: int
    conversations: int
    memories: int
    voice_sessions: int
    total_tokens: int
    rag_bytes: int
    last_active: str | None


class AdminStatsResponse(BaseModel):
    total_users: int
    total_conversations: int
    total_messages: int
    total_memories: int
    total_voice_sessions: int
    total_tokens: int
    total_rag_bytes: int
    source_breakdown: SourceBreakdown
    messages_per_day: list[DayCount]
    users: list[UserStats]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStatsResponse)
async def admin_stats(
    _admin: uuid.UUID = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate platform stats and per-user breakdowns."""

    # -- Exclude test/example users from all stats -----------------------
    _email_filter = not_(or_(*(User.email.ilike(f"%{d}") for d in EXCLUDED_DOMAINS)))
    excluded_ids_q = select(User.id).where(not_(_email_filter))
    excluded_ids = set((await db.execute(excluded_ids_q)).scalars().all())

    def _not_excluded(user_id_col):
        """Filter clause: user_id NOT in excluded set."""
        if not excluded_ids:
            return True  # no-op when nothing to exclude
        return not_(user_id_col.in_(excluded_ids))

    # -- Aggregate counts ------------------------------------------------
    total_users = (await db.execute(
        select(func.count(User.id)).where(_email_filter)
    )).scalar_one()
    total_conversations = (await db.execute(
        select(func.count(Conversation.id)).where(_not_excluded(Conversation.user_id))
    )).scalar_one()
    total_messages = (await db.execute(
        select(func.count(Message.id)).where(_not_excluded(Message.user_id))
    )).scalar_one()
    total_memories = (await db.execute(
        select(func.count(MemoryEmbedding.id)).where(_not_excluded(MemoryEmbedding.user_id))
    )).scalar_one()
    total_voice_sessions = (await db.execute(
        select(func.count(VoiceSession.id)).where(_not_excluded(VoiceSession.user_id))
    )).scalar_one()

    # -- Total token usage -----------------------------------------------
    total_tokens = (await db.execute(
        select(func.coalesce(func.sum(TokenUsage.total_tokens), 0))
        .where(_not_excluded(TokenUsage.user_id))
    )).scalar_one()

    # -- Total RAG disk space (actual on-disk bytes via pg_column_size) --
    if excluded_ids:
        id_list = ",".join(f"'{uid}'" for uid in excluded_ids)
        rag_total_sql = f"SELECT COALESCE(SUM(pg_column_size(t.*)), 0) FROM memory_embeddings t WHERE t.user_id NOT IN ({id_list})"
    else:
        rag_total_sql = "SELECT COALESCE(SUM(pg_column_size(t.*)), 0) FROM memory_embeddings t"
    total_rag_bytes = (await db.execute(text(rag_total_sql))).scalar_one()

    # -- Source breakdown ------------------------------------------------
    src_q = (
        select(Message.source, func.count(Message.id))
        .where(_not_excluded(Message.user_id))
        .group_by(Message.source)
    )
    src_rows = (await db.execute(src_q)).all()
    src_map = {row[0]: row[1] for row in src_rows}
    source_breakdown = SourceBreakdown(
        text=src_map.get(MessageSource.TEXT, 0),
        voice=src_map.get(MessageSource.VOICE, 0),
        vision=src_map.get(MessageSource.VISION, 0),
    )

    # -- Messages per day (last 30 days) --------------------------------
    since = datetime.now(timezone.utc) - timedelta(days=30)
    day_q = (
        select(
            func.date_trunc("day", Message.created_at).label("day"),
            func.count(Message.id),
        )
        .where(Message.created_at >= since, _not_excluded(Message.user_id))
        .group_by("day")
        .order_by("day")
    )
    day_rows = (await db.execute(day_q)).all()
    messages_per_day = [
        DayCount(date=row[0].strftime("%Y-%m-%d"), count=row[1])
        for row in day_rows
    ]

    # -- Per-user stats --------------------------------------------------
    msg_count = (
        select(Message.user_id, func.count(Message.id).label("cnt"), func.max(Message.created_at).label("last"))
        .group_by(Message.user_id)
        .subquery()
    )
    conv_count = (
        select(Conversation.user_id, func.count(Conversation.id).label("cnt"))
        .group_by(Conversation.user_id)
        .subquery()
    )
    mem_count = (
        select(MemoryEmbedding.user_id, func.count(MemoryEmbedding.id).label("cnt"))
        .group_by(MemoryEmbedding.user_id)
        .subquery()
    )
    vs_count = (
        select(VoiceSession.user_id, func.count(VoiceSession.id).label("cnt"))
        .group_by(VoiceSession.user_id)
        .subquery()
    )
    tok_count = (
        select(TokenUsage.user_id, func.sum(TokenUsage.total_tokens).label("cnt"))
        .group_by(TokenUsage.user_id)
        .subquery()
    )
    # Per-user RAG bytes via raw SQL subquery (pg_column_size not in ORM)
    rag_sub = text(
        "SELECT user_id, COALESCE(SUM(pg_column_size(t.*)), 0) AS bytes "
        "FROM memory_embeddings t GROUP BY user_id"
    ).columns(
        column("user_id", PG_UUID(as_uuid=True)),
        column("bytes", BigInteger),
    ).subquery("rag_sub")

    user_q = (
        select(
            User.email,
            User.display_name,
            User.created_at,
            func.coalesce(msg_count.c.cnt, 0).label("messages"),
            func.coalesce(conv_count.c.cnt, 0).label("conversations"),
            func.coalesce(mem_count.c.cnt, 0).label("memories"),
            func.coalesce(vs_count.c.cnt, 0).label("voice_sessions"),
            func.coalesce(tok_count.c.cnt, 0).label("total_tokens"),
            func.coalesce(rag_sub.c.bytes, 0).label("rag_bytes"),
            msg_count.c.last.label("last_active"),
        )
        .where(_email_filter)
        .outerjoin(msg_count, User.id == msg_count.c.user_id)
        .outerjoin(conv_count, User.id == conv_count.c.user_id)
        .outerjoin(mem_count, User.id == mem_count.c.user_id)
        .outerjoin(vs_count, User.id == vs_count.c.user_id)
        .outerjoin(tok_count, User.id == tok_count.c.user_id)
        .outerjoin(rag_sub, User.id == rag_sub.c.user_id)
        .order_by(func.coalesce(msg_count.c.cnt, 0).desc())
    )
    user_rows = (await db.execute(user_q)).all()

    users = [
        UserStats(
            email=r.email,
            display_name=r.display_name,
            joined=r.created_at.strftime("%Y-%m-%d"),
            messages=r.messages,
            conversations=r.conversations,
            memories=r.memories,
            voice_sessions=r.voice_sessions,
            total_tokens=r.total_tokens,
            rag_bytes=r.rag_bytes,
            last_active=r.last_active.strftime("%Y-%m-%d %H:%M") if r.last_active else None,
        )
        for r in user_rows
    ]

    return AdminStatsResponse(
        total_users=total_users,
        total_conversations=total_conversations,
        total_messages=total_messages,
        total_memories=total_memories,
        total_voice_sessions=total_voice_sessions,
        total_tokens=total_tokens,
        total_rag_bytes=total_rag_bytes,
        source_breakdown=source_breakdown,
        messages_per_day=messages_per_day,
        users=users,
    )
