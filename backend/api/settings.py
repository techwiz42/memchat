"""User settings API endpoints.

GET   /api/settings        — Get current user's settings (auto-creates with defaults)
PATCH /api/settings        — Partial update of user settings
GET   /api/settings/voices — List available Omnia voices
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user_id
from config import settings
from models import get_db
from models.user_settings import UserSettings
from voice.omnia_client import OmniaVoiceClient, OmniaAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsOut(BaseModel):
    omnia_voice_name: str
    omnia_language_code: str
    llm_model: str
    llm_temperature: float
    llm_max_tokens: Optional[int]


class SettingsPatch(BaseModel):
    omnia_voice_name: Optional[str] = Field(None, max_length=100)
    omnia_language_code: Optional[str] = Field(None, max_length=10)
    llm_model: Optional[str] = Field(None, max_length=100)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    llm_max_tokens: Optional[int] = Field(None, ge=1, le=128000)


async def get_or_create_settings(db: AsyncSession, user_id: uuid.UUID) -> UserSettings:
    """Get user settings, creating with defaults if none exist."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if user_settings is None:
        user_settings = UserSettings(user_id=user_id)
        db.add(user_settings)
        await db.commit()
        await db.refresh(user_settings)
    return user_settings


@router.get("", response_model=SettingsOut)
async def get_settings(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's settings."""
    user_settings = await get_or_create_settings(db, user_id)
    return SettingsOut(
        omnia_voice_name=user_settings.omnia_voice_name,
        omnia_language_code=user_settings.omnia_language_code,
        llm_model=user_settings.llm_model,
        llm_temperature=user_settings.llm_temperature,
        llm_max_tokens=user_settings.llm_max_tokens,
    )


@router.patch("", response_model=SettingsOut)
async def update_settings(
    body: SettingsPatch,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Partially update the current user's settings."""
    user_settings = await get_or_create_settings(db, user_id)

    patch_data = body.model_dump(exclude_unset=True)
    if not patch_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    for field, value in patch_data.items():
        setattr(user_settings, field, value)

    await db.commit()
    await db.refresh(user_settings)

    return SettingsOut(
        omnia_voice_name=user_settings.omnia_voice_name,
        omnia_language_code=user_settings.omnia_language_code,
        llm_model=user_settings.llm_model,
        llm_temperature=user_settings.llm_temperature,
        llm_max_tokens=user_settings.llm_max_tokens,
    )


@router.get("/voices")
async def list_voices(user_id: uuid.UUID = Depends(get_current_user_id)):
    """List available Omnia TTS voices."""
    client = OmniaVoiceClient(api_key=settings.omnia_api_key)
    try:
        voices = await client.list_voices()
        return {"voices": voices}
    except OmniaAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Omnia API error: {e.message}",
        )
