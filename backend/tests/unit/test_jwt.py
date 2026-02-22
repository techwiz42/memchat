"""Tests for auth.jwt: create/decode tokens, expiry, type validation."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from auth.jwt import (
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from config import settings


class TestCreateAccessToken:
    def test_returns_valid_jwt(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        payload = pyjwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
        assert payload["sub"] == str(uid)
        assert payload["type"] == "access"

    def test_expiry_is_set(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        payload = pyjwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        # Should expire roughly ACCESS_TOKEN_EXPIRE_MINUTES from now
        expected = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        assert abs((exp - expected).total_seconds()) < 5


class TestCreateRefreshToken:
    def test_returns_valid_jwt_with_refresh_type(self):
        uid = uuid.uuid4()
        token = create_refresh_token(uid)
        payload = pyjwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
        assert payload["sub"] == str(uid)
        assert payload["type"] == "refresh"

    def test_expiry_is_longer_than_access(self):
        uid = uuid.uuid4()
        token = create_refresh_token(uid)
        payload = pyjwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        assert abs((exp - expected).total_seconds()) < 5


class TestDecodeToken:
    def test_access_token_round_trip(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        assert decode_token(token, expected_type="access") == uid

    def test_refresh_token_round_trip(self):
        uid = uuid.uuid4()
        token = create_refresh_token(uid)
        assert decode_token(token, expected_type="refresh") == uid

    def test_wrong_type_raises_401(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="refresh")
        assert exc_info.value.status_code == 401
        assert "token type" in exc_info.value.detail.lower()

    def test_expired_token_raises_401(self):
        uid = uuid.uuid4()
        payload = {
            "sub": str(uid),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
            "type": "access",
        }
        token = pyjwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="access")
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_bad_signature_raises_401(self):
        uid = uuid.uuid4()
        payload = {
            "sub": str(uid),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "type": "access",
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="access")
        assert exc_info.value.status_code == 401

    def test_missing_sub_raises_401(self):
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "type": "access",
        }
        token = pyjwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="access")
        assert exc_info.value.status_code == 401

    def test_invalid_uuid_in_sub_raises_401(self):
        payload = {
            "sub": "not-a-uuid",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "type": "access",
        }
        token = pyjwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="access")
        assert exc_info.value.status_code == 401
