"""Tests for voice.session_manager (Redis-backed session tokens)."""

import uuid

import pytest

from voice.session_manager import (
    SESSION_PREFIX,
    USER_SESSION_PREFIX,
    create_session,
    validate_session,
    end_session,
    end_session_by_user,
)


class TestCreateSession:
    async def test_creates_token(self, fake_redis):
        uid = uuid.uuid4()
        token = await create_session(uid)
        assert isinstance(token, str)
        assert len(token) == 36  # UUID format

        # Verify Redis keys
        stored_uid = await fake_redis.get(f"{SESSION_PREFIX}{token}")
        assert stored_uid == str(uid)
        stored_token = await fake_redis.get(f"{USER_SESSION_PREFIX}{uid}")
        assert stored_token == token

    async def test_one_per_user(self, fake_redis):
        uid = uuid.uuid4()
        token1 = await create_session(uid)
        token2 = await create_session(uid)

        # First token should be gone
        assert await fake_redis.get(f"{SESSION_PREFIX}{token1}") is None
        # Second token is valid
        assert await fake_redis.get(f"{SESSION_PREFIX}{token2}") == str(uid)

    async def test_ttl_is_set(self, fake_redis):
        uid = uuid.uuid4()
        token = await create_session(uid)
        ttl = await fake_redis.ttl(f"{SESSION_PREFIX}{token}")
        assert 0 < ttl <= 1800


class TestValidateSession:
    async def test_valid_token(self, fake_redis):
        uid = uuid.uuid4()
        token = await create_session(uid)
        result = await validate_session(token)
        assert result == uid

    async def test_invalid_token_raises(self, fake_redis):
        with pytest.raises(ValueError, match="Invalid or expired"):
            await validate_session("nonexistent-token")

    async def test_expired_token_raises(self, fake_redis):
        """Manually set a token with 0 TTL to simulate expiry."""
        await fake_redis.setex(f"{SESSION_PREFIX}expired-tok", 1, str(uuid.uuid4()))
        import asyncio
        await asyncio.sleep(1.1)
        with pytest.raises(ValueError):
            await validate_session("expired-tok")


class TestEndSession:
    async def test_end_by_token(self, fake_redis):
        uid = uuid.uuid4()
        token = await create_session(uid)
        await end_session(token)
        assert await fake_redis.get(f"{SESSION_PREFIX}{token}") is None
        assert await fake_redis.get(f"{USER_SESSION_PREFIX}{uid}") is None

    async def test_end_nonexistent_is_noop(self, fake_redis):
        await end_session("does-not-exist")  # Should not raise


class TestEndSessionByUser:
    async def test_end_by_user(self, fake_redis):
        uid = uuid.uuid4()
        token = await create_session(uid)
        await end_session_by_user(uid)
        assert await fake_redis.get(f"{SESSION_PREFIX}{token}") is None
        assert await fake_redis.get(f"{USER_SESSION_PREFIX}{uid}") is None

    async def test_end_no_session_is_noop(self, fake_redis):
        await end_session_by_user(uuid.uuid4())  # Should not raise
