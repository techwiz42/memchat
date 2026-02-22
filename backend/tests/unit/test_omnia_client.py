"""Tests for voice.omnia_client.OmniaVoiceClient using respx."""

import pytest
import respx
from httpx import Response

from voice.omnia_client import OmniaVoiceClient, OmniaAPIError, OMNIA_BASE_URL


@pytest.fixture
def client():
    return OmniaVoiceClient(api_key="test-key")


class TestOmniaClientHeaders:
    async def test_sends_api_key_header(self, client):
        with respx.mock:
            route = respx.get(f"{OMNIA_BASE_URL}/voices").mock(
                return_value=Response(200, json=[])
            )
            await client.list_voices()
            assert route.called
            request = route.calls[0].request
            assert request.headers["x-api-key"] == "test-key"
            assert request.headers["accept"] == "application/json"


class TestCreateInlineCall:
    async def test_success(self, client):
        with respx.mock:
            respx.post(f"{OMNIA_BASE_URL}/calls/inline").mock(
                return_value=Response(200, json={"callId": "c1", "joinUrl": "wss://join"})
            )
            result = await client.create_inline_call({"systemPrompt": "test"})
            assert result["callId"] == "c1"
            assert result["joinUrl"] == "wss://join"

    async def test_posts_json_body(self, client):
        with respx.mock:
            route = respx.post(f"{OMNIA_BASE_URL}/calls/inline").mock(
                return_value=Response(200, json={"callId": "c1", "joinUrl": "wss://j"})
            )
            await client.create_inline_call({"systemPrompt": "hello"})
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["systemPrompt"] == "hello"


class TestGetCall:
    async def test_success(self, client):
        with respx.mock:
            respx.get(f"{OMNIA_BASE_URL}/calls/call-123").mock(
                return_value=Response(200, json={"transcript": "Hi", "summary": "Greeting"})
            )
            result = await client.get_call("call-123")
            assert result["transcript"] == "Hi"


class TestListVoices:
    async def test_returns_list(self, client):
        with respx.mock:
            respx.get(f"{OMNIA_BASE_URL}/voices").mock(
                return_value=Response(200, json=[{"name": "Mark"}])
            )
            voices = await client.list_voices()
            assert voices == [{"name": "Mark"}]

    async def test_unwraps_dict_response(self, client):
        with respx.mock:
            respx.get(f"{OMNIA_BASE_URL}/voices").mock(
                return_value=Response(200, json={"voices": [{"name": "Sarah"}]})
            )
            voices = await client.list_voices()
            assert voices == [{"name": "Sarah"}]


class TestErrorHandling:
    async def test_400_raises_omnia_error(self, client):
        with respx.mock:
            respx.post(f"{OMNIA_BASE_URL}/calls/inline").mock(
                return_value=Response(400, json={"error": "Bad config"})
            )
            with pytest.raises(OmniaAPIError) as exc_info:
                await client.create_inline_call({})
            assert exc_info.value.status_code == 400
            assert "Bad config" in exc_info.value.message

    async def test_500_raises_omnia_error(self, client):
        with respx.mock:
            respx.get(f"{OMNIA_BASE_URL}/calls/c1").mock(
                return_value=Response(500, json={"message": "Internal error"})
            )
            with pytest.raises(OmniaAPIError) as exc_info:
                await client.get_call("c1")
            assert exc_info.value.status_code == 500

    async def test_nested_error_dict(self, client):
        with respx.mock:
            respx.post(f"{OMNIA_BASE_URL}/calls/inline").mock(
                return_value=Response(422, json={"error": {"message": "Validation failed"}})
            )
            with pytest.raises(OmniaAPIError) as exc_info:
                await client.create_inline_call({})
            assert "Validation failed" in exc_info.value.message

    async def test_204_returns_empty_dict(self, client):
        with respx.mock:
            respx.get(f"{OMNIA_BASE_URL}/calls/c1").mock(
                return_value=Response(204)
            )
            result = await client.get_call("c1")
            assert result == {}
