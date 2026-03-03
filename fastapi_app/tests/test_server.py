"""Tests for MCPServer.handle_message."""

from unittest.mock import AsyncMock

import pytest

from fastapi_app.mcp.permissions import MCPPermissionChecker
from fastapi_app.mcp.server import MCPServer, _sanitize_params


class TestSanitizeParams:
    def test_masks_password(self):
        result = _sanitize_params({"password": "secret123"})
        assert result["password"] == "***"

    def test_masks_token(self):
        result = _sanitize_params({"auth_token": "abc"})
        assert result["auth_token"] == "***"

    def test_masks_api_key(self):
        result = _sanitize_params({"api_key": "xyz"})
        assert result["api_key"] == "***"

    def test_masks_nested(self):
        # "config" is not a sensitive key, so value should be recursed
        result = _sanitize_params({"config": {"password": "secret"}})
        assert result["config"]["password"] == "***"

    def test_preserves_normal(self):
        result = _sanitize_params({"name": "test", "count": 5})
        assert result == {"name": "test", "count": 5}

    def test_non_dict_returns_empty(self):
        result = _sanitize_params("not a dict")
        assert result == {}


class TestFormatResult:
    def setup_method(self):
        self.server = MCPServer(account_id=1)

    def test_dict_to_json(self):
        result = self.server._format_result({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_str_passthrough(self):
        result = self.server._format_result("plain text")
        assert result == "plain text"


@pytest.mark.asyncio
class TestMCPServerHandleMessage:
    def _make_server(self, mode="safe", is_admin=False):
        """Create MCPServer with mock permissions and tools."""
        server = MCPServer(account_id=1, mode=mode, is_admin=is_admin)
        server.permissions = MCPPermissionChecker(
            account_id=1, mode=mode, is_admin=is_admin
        )
        server._initialized = True

        # Populate tools
        async def mock_handler(ctx, **kwargs):
            return {"data": [{"id": 1}]}

        server._tools = {
            "testsys_users_list": {
                "name": "testsys_users_list",
                "description": "List users",
                "tool_type": "system_read",
                "input_schema": {"type": "object"},
                "handler": mock_handler,
            },
            "testsys_users_create": {
                "name": "testsys_users_create",
                "description": "Create user",
                "tool_type": "system_write",
                "input_schema": {"type": "object"},
                "handler": mock_handler,
            },
        }
        # Mock DB so audit logging doesn't fail
        server.db = AsyncMock()
        return server

    async def test_handle_initialize(self):
        server = MCPServer(account_id=1, db=AsyncMock())
        # Patch initialize to skip real DB tool loading
        server._tools = {}
        server.permissions = MCPPermissionChecker(account_id=1)

        async def fake_init():
            server._initialized = True

        server.initialize = fake_init

        response = await server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response["result"]["protocolVersion"] == MCPServer.PROTOCOL_VERSION
        assert response["result"]["serverInfo"]["name"] == MCPServer.SERVER_NAME
        assert "capabilities" in response["result"]

    async def test_handle_initialized_notification(self):
        server = self._make_server()
        response = await server.handle_message({"jsonrpc": "2.0", "method": "initialized"})
        assert response is None

    async def test_handle_ping(self):
        server = self._make_server()
        response = await server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert response["result"] == {}

    async def test_handle_tools_list(self):
        server = self._make_server(mode="power")
        response = await server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        tools = response["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "testsys_users_list" in names
        assert "testsys_users_create" in names

    async def test_handle_tools_list_safe_mode(self):
        server = self._make_server(mode="safe")
        response = await server.handle_message({"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
        tools = response["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "testsys_users_list" in names
        # system_write should be excluded in safe mode
        assert "testsys_users_create" not in names

    async def test_handle_tools_call_success(self):
        server = self._make_server(mode="power")
        response = await server.handle_message({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "testsys_users_list", "arguments": {}},
        })
        assert "result" in response
        assert response["result"]["content"][0]["type"] == "text"

    async def test_handle_tools_call_unknown_tool(self):
        server = self._make_server()
        response = await server.handle_message({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        })
        assert response["error"]["code"] == -32603

    async def test_handle_tools_call_no_name(self):
        server = self._make_server()
        response = await server.handle_message({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"arguments": {}},
        })
        assert response["error"]["code"] == -32603

    async def test_handle_tools_call_permission_denied(self):
        server = self._make_server(mode="safe")
        response = await server.handle_message({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "testsys_users_create", "arguments": {}},
        })
        # Permission denied → error
        assert response["error"]["code"] == -32603

    async def test_handle_unknown_method(self):
        server = self._make_server()
        response = await server.handle_message({
            "jsonrpc": "2.0",
            "id": 9,
            "method": "unknown/method",
        })
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]
