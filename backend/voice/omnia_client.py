"""
Omnia Voice API Client

Async HTTP client wrapping Omnia's REST API for inline call creation,
call retrieval, and voice/language discovery.

Adapted from agent_framework's omnia_voice_client.py — stripped to only
the endpoints memchat needs: create_inline_call, get_call, list_voices,
list_languages.

API Base URL: https://dashboard.omnia-voice.com/api/v1
Auth: X-API-Key header
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OMNIA_BASE_URL = "https://dashboard.omnia-voice.com/api/v1"


class OmniaAPIError(Exception):
    """Raised when Omnia API returns an error response."""

    def __init__(self, status_code: int, message: str, response_body: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"Omnia API error {status_code}: {message}")


class OmniaVoiceClient:
    """Async HTTP client for Omnia Voice REST API."""

    def __init__(self, api_key: str, base_url: str = OMNIA_BASE_URL, timeout: float = 30.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to Omnia API."""
        url = f"{self.base_url}{path}"
        logger.info(f"Omnia API request: {method} {url}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self._headers(),
                json=json_body,
                params=params,
            )

        logger.info(f"Omnia API response: {response.status_code}")

        if response.status_code >= 400:
            logger.error(f"Omnia API error response body: {response.text[:2000]}")
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}

            error_msg = response.text
            if isinstance(body.get("error"), dict):
                error_msg = body["error"].get("message", error_msg)
            elif isinstance(body.get("error"), str):
                error_msg = body["error"]
                if body.get("details"):
                    import json
                    error_msg += f" | {json.dumps(body['details'])}"
            elif body.get("message"):
                error_msg = body["message"]

            raise OmniaAPIError(
                status_code=response.status_code,
                message=error_msg,
                response_body=body,
            )

        if response.status_code == 204:
            return {}
        return response.json()

    async def create_inline_call(self, inline_config: dict[str, Any]) -> dict[str, Any]:
        """Create a call with inline agent configuration.

        Args:
            inline_config: Full inline call config including prompt, voice, tools, etc.

        Returns:
            Call object with 'callId' and 'joinUrl' fields.
        """
        return await self._request("POST", "/calls/inline", json_body=inline_config)

    async def get_call(self, call_id: str) -> dict[str, Any]:
        """Get call details including transcript and summary.

        Args:
            call_id: Omnia call ID.

        Returns:
            Call object with transcript, summary, duration, etc.
        """
        return await self._request("GET", f"/calls/{call_id}")

    async def list_voices(self) -> list[dict[str, Any]]:
        """List available TTS voices."""
        result = await self._request("GET", "/voices")
        if isinstance(result, list):
            return result
        return result.get("voices", result.get("data", []))

    async def list_languages(self) -> list[dict[str, Any]]:
        """List supported languages."""
        result = await self._request("GET", "/languages")
        if isinstance(result, list):
            return result
        return result.get("languages", result.get("data", []))
