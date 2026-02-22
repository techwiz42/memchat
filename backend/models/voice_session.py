"""Voice session tracking model."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VoiceSessionStatus(str, enum.Enum):
    ACTIVE = "active"
    ENDED = "ended"
    ERROR = "error"


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    omnia_call_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[VoiceSessionStatus] = mapped_column(
        Enum(VoiceSessionStatus), nullable=False, default=VoiceSessionStatus.ACTIVE
    )
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
