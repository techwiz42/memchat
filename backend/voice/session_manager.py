"""Redis-backed voice session token management.

Session tokens are random UUIDs stored in Redis with a 30-minute TTL.
They map token → user_id and are used to authenticate Omnia tool callbacks
(since Omnia is the caller, not the user's browser, JWT auth doesn't apply).

One active session per user is enforced.
"""

import uuid
import logging

import redis.asyncio as redis

from config import settings

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 1800  # 30 minutes
SESSION_PREFIX = "voice_session:"
USER_SESSION_PREFIX = "user_voice_session:"

_redis_pool: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_pool


async def create_session(user_id: uuid.UUID) -> str:
    """Create a new voice session token for a user.

    Ends any existing session for this user first (one active session per user).

    Args:
        user_id: The user's ID.

    Returns:
        The session token string.
    """
    r = _get_redis()
    user_id_str = str(user_id)

    # End any existing session for this user
    existing_token = await r.get(f"{USER_SESSION_PREFIX}{user_id_str}")
    if existing_token:
        await r.delete(f"{SESSION_PREFIX}{existing_token}")
        logger.info(f"Ended existing voice session for user {user_id_str}")

    # Create new session
    token = str(uuid.uuid4())
    pipe = r.pipeline()
    pipe.setex(f"{SESSION_PREFIX}{token}", SESSION_TTL_SECONDS, user_id_str)
    pipe.setex(f"{USER_SESSION_PREFIX}{user_id_str}", SESSION_TTL_SECONDS, token)
    await pipe.execute()

    logger.info(f"Created voice session for user {user_id_str}")
    return token


async def validate_session(token: str) -> uuid.UUID:
    """Validate a session token and return the associated user_id.

    Args:
        token: The session token to validate.

    Returns:
        The user's UUID.

    Raises:
        ValueError: If the token is invalid or expired.
    """
    r = _get_redis()
    user_id_str = await r.get(f"{SESSION_PREFIX}{token}")
    if not user_id_str:
        raise ValueError("Invalid or expired voice session token")
    return uuid.UUID(user_id_str)


async def end_session(token: str) -> None:
    """End a voice session by token.

    Args:
        token: The session token to end.
    """
    r = _get_redis()
    user_id_str = await r.get(f"{SESSION_PREFIX}{token}")
    if user_id_str:
        await r.delete(f"{USER_SESSION_PREFIX}{user_id_str}")
    await r.delete(f"{SESSION_PREFIX}{token}")
    logger.info(f"Ended voice session (token={token[:8]}...)")


async def end_session_by_user(user_id: uuid.UUID) -> None:
    """End a voice session by user ID.

    Looks up the user's active session token in Redis and cleans up both keys.

    Args:
        user_id: The user's UUID.
    """
    r = _get_redis()
    user_id_str = str(user_id)
    token = await r.get(f"{USER_SESSION_PREFIX}{user_id_str}")
    if token:
        await r.delete(f"{SESSION_PREFIX}{token}")
        await r.delete(f"{USER_SESSION_PREFIX}{user_id_str}")
        logger.info(f"Ended voice session for user {user_id_str}")
