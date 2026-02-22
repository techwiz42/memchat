"""Tests for voice.omnia_config: build_inline_call_config structure."""

from voice.omnia_config import build_inline_call_config, build_tool_definitions


class TestBuildToolDefinitions:
    def test_returns_two_tools(self):
        tools = build_tool_definitions("https://example.com", "tok-1", "uid-1")
        assert len(tools) == 2

    def test_rag_query_tool_structure(self):
        tools = build_tool_definitions("https://example.com", "tok-1", "uid-1")
        rag = tools[0]["temporaryTool"]
        assert rag["modelToolName"] == "rag_query"
        assert rag["http"]["httpMethod"] == "POST"
        assert "/api/voice-tools/rag-query" in rag["http"]["baseUrlPattern"]

    def test_store_memory_tool_structure(self):
        tools = build_tool_definitions("https://example.com", "tok-1", "uid-1")
        store = tools[1]["temporaryTool"]
        assert store["modelToolName"] == "store_memory"
        assert store["http"]["httpMethod"] == "POST"
        assert "/api/voice-tools/store-memory" in store["http"]["baseUrlPattern"]

    def test_session_token_in_static_params(self):
        tools = build_tool_definitions("https://example.com", "my-token", "uid-1")
        tool = tools[0]["temporaryTool"]
        auth_param = [p for p in tool["staticParameters"] if p["name"] == "Authorization"]
        assert len(auth_param) == 1
        assert auth_param[0]["value"] == "Bearer my-token"

    def test_base_url_in_http(self):
        tools = build_tool_definitions("https://app.test", "tok", "uid")
        assert tools[0]["temporaryTool"]["http"]["baseUrlPattern"].startswith("https://app.test")


class TestBuildInlineCallConfig:
    def test_config_structure(self):
        config = build_inline_call_config("tok-1", "uid-1")
        assert "systemPrompt" in config
        assert config["voice"] == "Mark"  # default
        assert config["language"] == "en"
        assert config["firstSpeaker"] == "agent"
        assert config["connectionType"] == "webrtc"
        assert config["temperature"] == 0.4
        assert config["maxDuration"] == 1800

    def test_greeting_present(self):
        config = build_inline_call_config("tok-1", "uid-1")
        assert "greeting" in config
        assert len(config["greeting"]) > 0

    def test_selected_tools_included(self):
        config = build_inline_call_config("tok-1", "uid-1")
        assert "selectedTools" in config
        assert len(config["selectedTools"]) == 2
