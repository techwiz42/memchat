"""Tests for /api/voice/* endpoints: start, end, voices."""

from unittest.mock import AsyncMock, patch

import pytest

from voice.omnia_client import OmniaAPIError


class TestStartVoiceSession:
    @pytest.fixture(autouse=True)
    def _patch(self, fake_redis):
        with (
            patch("api.voice.create_session", new_callable=AsyncMock, return_value="tok-123") as cs,
            patch("api.voice.build_inline_call_config", return_value={"systemPrompt": "..."}) as bic,
            patch("api.voice.OmniaVoiceClient") as OVC,
        ):
            self.mock_client = AsyncMock()
            OVC.return_value = self.mock_client
            self.create_session = cs
            self.build_config = bic
            yield

    async def test_start_success(self, test_client, auth_headers, registered_user):
        self.mock_client.create_inline_call.return_value = {
            "callId": "call-1",
            "joinUrl": "wss://omnia.example/join",
        }
        resp = await test_client.post("/api/voice/start", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["call_id"] == "call-1"
        assert data["join_url"] == "wss://omnia.example/join"

    async def test_start_omnia_failure_returns_502(self, test_client, auth_headers):
        self.mock_client.create_inline_call.side_effect = OmniaAPIError(500, "Omnia down")
        resp = await test_client.post("/api/voice/start", headers=auth_headers)
        assert resp.status_code == 502
        assert "omnia" in resp.json()["detail"].lower()

    async def test_start_bad_format_returns_502(self, test_client, auth_headers):
        self.mock_client.create_inline_call.return_value = {"unexpected": "data"}
        resp = await test_client.post("/api/voice/start", headers=auth_headers)
        assert resp.status_code == 502
        assert "unexpected" in resp.json()["detail"].lower()


class TestEndVoiceSession:
    @pytest.fixture(autouse=True)
    def _patch(self, fake_redis):
        with (
            patch("api.voice.end_session_by_user", new_callable=AsyncMock),
            patch("api.voice.OmniaVoiceClient") as OVC,
        ):
            self.mock_client = AsyncMock()
            OVC.return_value = self.mock_client
            yield

    async def _create_voice_session(self, db_session, user_id, call_id="call-1"):
        from models.voice_session import VoiceSession
        vs = VoiceSession(user_id=user_id, omnia_call_id=call_id)
        db_session.add(vs)
        await db_session.commit()
        return vs

    async def test_end_success(self, test_client, auth_headers, registered_user, db_session):
        await self._create_voice_session(db_session, registered_user["id"])
        self.mock_client.get_call.return_value = {
            "transcript": "Hello world",
            "summary": "Greeting exchanged",
        }
        resp = await test_client.post(
            "/api/voice/end",
            json={"call_id": "call-1"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcript"] == "Hello world"
        assert data["summary"] == "Greeting exchanged"

    async def test_end_unknown_call_returns_404(self, test_client, auth_headers):
        resp = await test_client.post(
            "/api/voice/end",
            json={"call_id": "nonexistent"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_end_omnia_failure_still_succeeds(self, test_client, auth_headers, registered_user, db_session):
        """If Omnia fails to return call data, endpoint still returns 200 with null fields."""
        await self._create_voice_session(db_session, registered_user["id"])
        self.mock_client.get_call.side_effect = OmniaAPIError(500, "down")
        resp = await test_client.post(
            "/api/voice/end",
            json={"call_id": "call-1"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcript"] is None
        assert data["summary"] is None


class TestListVoices:
    async def test_list_voices(self, test_client, auth_headers):
        with patch("api.voice.OmniaVoiceClient") as OVC:
            mock_client = AsyncMock()
            mock_client.list_voices.return_value = [{"name": "Mark"}, {"name": "Sarah"}]
            OVC.return_value = mock_client

            resp = await test_client.get("/api/voice/voices", headers=auth_headers)
            assert resp.status_code == 200
            assert len(resp.json()["voices"]) == 2
