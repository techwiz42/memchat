"""
Memchat-specific Omnia inline call configuration.

Builds the inline call config with two tools:
  - rag_query: retrieves context from the user's knowledge base
  - store_memory: stores new information in the user's memory

The browser connects to Omnia directly via WebRTC (ultravox-client SDK).
Omnia calls our backend tool endpoints when the LLM decides to use them.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from models.conversation import Message

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful personal assistant having a voice conversation with the user.
You have access to the user's personal knowledge base through the rag_query tool. Use it when:
- The user asks about something they may have previously told you
- The user references past conversations, notes, or stored information
- You need context about the user's preferences, projects, or personal details

You can also store new information the user shares using the store_memory tool. Use it when:
- The user explicitly asks you to remember something
- The user shares important personal information (preferences, goals, key facts)
- The user provides information they'd want to recall later

Be conversational, warm, and concise. This is a voice conversation — keep responses natural and
spoken-word friendly. Avoid long lists or overly structured responses. If you don't have relevant
information from the knowledge base, say so honestly and offer to help in other ways.

You are an intellectually curious conversationalist.
Prioritize insight over summary.
Offer unexpected connections.
Ask one thoughtful follow-up question when appropriate.
Speak as if speaking to a founder or philosopher, not a casual user."""


def build_tool_definitions(base_url: str, session_token: str, user_id: str) -> list[dict[str, Any]]:
    """Build Omnia tool definitions for memchat.

    Args:
        base_url: Public base URL for tool callback endpoints.
        session_token: Voice session token for authenticating tool callbacks.
        user_id: User ID passed as static parameter.

    Returns:
        List of Omnia selectedTools definitions.
    """
    static_params = [
        {"name": "user_id", "location": "PARAMETER_LOCATION_BODY", "value": user_id},
        {
            "name": "Authorization",
            "location": "PARAMETER_LOCATION_HEADER",
            "value": f"Bearer {session_token}",
        },
    ]

    rag_query_tool = {
        "temporaryTool": {
            "modelToolName": "rag_query",
            "description": (
                "Search the user's personal knowledge base for relevant information. "
                "Use this when the user asks about something they may have previously shared, "
                "or when you need context about the user's stored memories and notes."
            ),
            "dynamicParameters": [
                {
                    "name": "query",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": {
                        "type": "string",
                        "description": "The search query to find relevant memories",
                    },
                    "required": True,
                },
            ],
            "automaticParameters": [
                {
                    "name": "call_id",
                    "location": "PARAMETER_LOCATION_BODY",
                    "knownValue": "KNOWN_PARAM_CALL_ID",
                },
            ],
            "staticParameters": static_params,
            "http": {
                "baseUrlPattern": f"{base_url}/api/voice-tools/rag-query",
                "httpMethod": "POST",
            },
            "timeout": "15s",
        },
    }

    store_memory_tool = {
        "temporaryTool": {
            "modelToolName": "store_memory",
            "description": (
                "Store new information in the user's personal knowledge base. "
                "Use this when the user asks you to remember something, or when they share "
                "important information they'd want to recall later."
            ),
            "dynamicParameters": [
                {
                    "name": "content",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": {
                        "type": "string",
                        "description": "The information to store in the user's memory",
                    },
                    "required": True,
                },
            ],
            "automaticParameters": [
                {
                    "name": "call_id",
                    "location": "PARAMETER_LOCATION_BODY",
                    "knownValue": "KNOWN_PARAM_CALL_ID",
                },
            ],
            "staticParameters": static_params,
            "http": {
                "baseUrlPattern": f"{base_url}/api/voice-tools/store-memory",
                "httpMethod": "POST",
            },
            "timeout": "15s",
        },
    }

    return [rag_query_tool, store_memory_tool]


def _build_context_prompt(recent_messages: list[Message]) -> str:
    """Build the system prompt, injecting recent conversation context if available."""
    if not recent_messages:
        return SYSTEM_PROMPT

    lines = []
    for msg in recent_messages:
        prefix = "User" if msg.role == "user" else "Assistant"
        # Truncate long messages to keep prompt reasonable
        content = msg.content[:500]
        lines.append(f"{prefix}: {content}")

    context_block = "\n".join(lines)

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"--- Recent conversation context (text chat) ---\n"
        f"The user was just chatting via text before switching to voice. "
        f"Here is their recent conversation for continuity:\n\n"
        f"{context_block}\n\n"
        f"Continue naturally from this context. Don't repeat what was already said, "
        f"but be aware of it."
    )


def build_inline_call_config(
    session_token: str,
    user_id: str,
    recent_messages: list[Message] | None = None,
    *,
    voice_name: str | None = None,
    language_code: str | None = None,
) -> dict[str, Any]:
    """Build the full Omnia inline call configuration for a memchat voice session.

    Args:
        session_token: Voice session token for tool callback auth.
        user_id: User ID string.
        recent_messages: Recent conversation messages for continuity across modes.
        voice_name: Per-user voice override. Falls back to global settings.
        language_code: Per-user language override. Falls back to global settings.

    Returns:
        Omnia inline call configuration dict ready for create_inline_call().
    """
    base_url = settings.public_base_url.rstrip("/")

    tool_definitions = build_tool_definitions(base_url, session_token, user_id)
    system_prompt = _build_context_prompt(recent_messages or [])

    return {
        "systemPrompt": system_prompt,
        "model": settings.llm_model,
        "voice": voice_name or settings.omnia_voice_name,
        "language": language_code or settings.omnia_language_code,
        "greeting": "Hey there! How can I help you today?",
        "firstSpeaker": "agent",
        "temperature": 0.7,
        "maxDuration": 1800,
        "connectionType": "webrtc",
        "selectedTools": tool_definitions,
    }
