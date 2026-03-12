"""Tests for gateway.mcp_server — permission checks, sanitization, JSON-RPC handling."""

from dataclasses import dataclass, field

import pytest
from gateway.mcp_server import (
    MCPSession,
    _handle_message,
    _is_tool_allowed,
    _sanitize_params,
)

from .conftest import create_test_data

# ---------------------------------------------------------------------------
# Lightweight stubs (avoid SQLAlchemy __new__ issues)
# ---------------------------------------------------------------------------


@dataclass
class _StubApiKey:
    id: int = 1
    account_id: int = 1
    mode: str = "safe"
    allowed_tools: list = field(default_factory=list)
    blocked_tools: list = field(default_factory=list)


def _make_session(tools=None, api_key=None, project=None) -> MCPSession:
    if api_key is None:
        api_key = _StubApiKey()
    return MCPSession(
        id="test-session-id",
        account_id=1,
        api_key_id=api_key.id,
        api_key_obj=api_key,
        project=project,
        mode=api_key.mode or "safe",
        tools=tools or [],
    )


# ---------------------------------------------------------------------------
# _is_tool_allowed
# ---------------------------------------------------------------------------


class TestIsToolAllowed:
    def test_safe_mode_blocks_write(self):
        key = _StubApiKey(mode="safe")
        tool = {"name": "sys_users_create", "tool_type": "system_write"}
        assert _is_tool_allowed(tool, key) is False

    def test_safe_mode_allows_read(self):
        key = _StubApiKey(mode="safe")
        tool = {"name": "sys_users_list", "tool_type": "system_read"}
        assert _is_tool_allowed(tool, key) is True

    def test_full_mode_allows_write(self):
        key = _StubApiKey(mode="full")
        tool = {"name": "sys_users_create", "tool_type": "system_write"}
        assert _is_tool_allowed(tool, key) is True

    def test_whitelist_allows_listed(self):
        key = _StubApiKey(mode="full", allowed_tools=["sys_users_list"])
        tool = {"name": "sys_users_list", "tool_type": "system_read"}
        assert _is_tool_allowed(tool, key) is True

    def test_whitelist_blocks_unlisted(self):
        key = _StubApiKey(mode="full", allowed_tools=["sys_users_list"])
        tool = {"name": "sys_users_create", "tool_type": "system_write"}
        assert _is_tool_allowed(tool, key) is False

    def test_blacklist_blocks(self):
        key = _StubApiKey(mode="full", blocked_tools=["sys_users_delete"])
        tool = {"name": "sys_users_delete", "tool_type": "system_write"}
        assert _is_tool_allowed(tool, key) is False

    def test_blacklist_does_not_block_others(self):
        key = _StubApiKey(mode="full", blocked_tools=["sys_users_delete"])
        tool = {"name": "sys_users_list", "tool_type": "system_read"}
        assert _is_tool_allowed(tool, key) is True

    def test_default_mode_is_safe(self):
        key = _StubApiKey(mode=None)
        tool = {"name": "sys_users_create", "tool_type": "system_write"}
        assert _is_tool_allowed(tool, key) is False


# ---------------------------------------------------------------------------
# _sanitize_params
# ---------------------------------------------------------------------------


class TestSanitizeParams:
    def test_sensitive_keys_masked(self):
        result = _sanitize_params({"password": "secret123", "name": "Alice"})
        assert result["password"] == "***"
        assert result["name"] == "Alice"

    def test_nested_dict_sanitized(self):
        result = _sanitize_params({"config": {"api_key": "sk-123", "url": "http://x"}})
        assert result["config"]["api_key"] == "***"
        assert result["config"]["url"] == "http://x"

    def test_multiple_sensitive_keys(self):
        result = _sanitize_params(
            {
                "token": "abc",
                "secret": "def",
                "credential": "ghi",
                "auth": "jkl",
                "normal": "keep",
            }
        )
        assert result["token"] == "***"
        assert result["secret"] == "***"
        assert result["credential"] == "***"
        assert result["auth"] == "***"
        assert result["normal"] == "keep"

    def test_non_dict_returns_empty(self):
        assert _sanitize_params("not a dict") == {}
        assert _sanitize_params(42) == {}

    def test_empty_dict(self):
        assert _sanitize_params({}) == {}

    def test_case_insensitive_matching(self):
        result = _sanitize_params({"API_KEY": "x", "Password": "y"})
        assert result["API_KEY"] == "***"
        assert result["Password"] == "***"


# ---------------------------------------------------------------------------
# _handle_message (async, needs DB)
# ---------------------------------------------------------------------------


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_initialize(self, db):
        session = _make_session()
        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            session,
            db,
        )
        assert resp["id"] == 1
        assert "protocolVersion" in resp["result"]
        assert resp["result"]["serverInfo"]["name"] == "adapterly-gateway"

    @pytest.mark.asyncio
    async def test_initialized_returns_none(self, db):
        session = _make_session()
        resp = await _handle_message(
            {"jsonrpc": "2.0", "method": "initialized"},
            session,
            db,
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_ping(self, db):
        session = _make_session()
        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            session,
            db,
        )
        assert resp["result"] == {}

    @pytest.mark.asyncio
    async def test_tools_list_filters_by_permission(self, db):
        key = _StubApiKey(mode="safe")
        tools = [
            {
                "name": "sys_users_list",
                "tool_type": "system_read",
                "description": "List users",
                "input_schema": {"type": "object"},
            },
            {
                "name": "sys_users_create",
                "tool_type": "system_write",
                "description": "Create user",
                "input_schema": {"type": "object"},
            },
        ]
        session = _make_session(tools=tools, api_key=key)

        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            session,
            db,
        )
        result_tools = resp["result"]["tools"]
        assert len(result_tools) == 1
        assert result_tools[0]["name"] == "sys_users_list"

    @pytest.mark.asyncio
    async def test_tools_list_full_mode(self, db):
        key = _StubApiKey(mode="full")
        tools = [
            {"name": "sys_users_list", "tool_type": "system_read", "description": "List", "input_schema": {}},
            {"name": "sys_users_create", "tool_type": "system_write", "description": "Create", "input_schema": {}},
        ]
        session = _make_session(tools=tools, api_key=key)

        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            session,
            db,
        )
        assert len(resp["result"]["tools"]) == 2

    @pytest.mark.asyncio
    async def test_resources_list_empty(self, db):
        session = _make_session()
        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
            session,
            db,
        )
        assert resp["result"]["resources"] == []

    @pytest.mark.asyncio
    async def test_unknown_method(self, db):
        session = _make_session()
        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 6, "method": "nonexistent/method"},
            session,
            db,
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_tools_call_unknown_tool(self, db):
        await create_test_data(db)
        key = _StubApiKey(mode="full")
        session = _make_session(tools=[], api_key=key)

        resp = await _handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
            },
            session,
            db,
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_call_missing_name(self, db):
        session = _make_session()
        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {}},
            session,
            db,
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_list_output_format(self, db):
        key = _StubApiKey(mode="full")
        tools = [
            {
                "name": "sys_users_list",
                "tool_type": "system_read",
                "description": "List users",
                "input_schema": {"type": "object", "properties": {"page": {"type": "integer"}}},
                "action_id": 1,
                "system_alias": "sys",
            },
        ]
        session = _make_session(tools=tools, api_key=key)

        resp = await _handle_message(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
            session,
            db,
        )
        tool = resp["result"]["tools"][0]
        # Output should have only name, description, inputSchema
        assert set(tool.keys()) == {"name", "description", "inputSchema"}
        assert tool["inputSchema"]["type"] == "object"
