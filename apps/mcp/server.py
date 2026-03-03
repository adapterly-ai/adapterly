"""
MCP Server - Main server class for Adapterly MCP Gateway.

This is the core component that:
- Handles MCP protocol messages
- Manages tool and resource registration
- Enforces permissions (Safe/Power mode)
- Logs all operations for audit
"""

import asyncio
import logging
from typing import Any

from apps.mcp.audit import MCPAuditLogger
from apps.mcp.permissions import get_permission_checker
from apps.mcp.resources import get_system_resources
from apps.mcp.sessions import MCPSessionManager, create_session_id
from apps.mcp.tools import MCPToolRegistry, get_audit_tools, get_business_tools, get_context_tools, get_system_tools

logger = logging.getLogger(__name__)


class MCPServer:
    """
    Adapterly MCP Server - MCP Tool Gateway.

    Provides MCP protocol implementation with:
    - System tools (MCP Gateway)
    - Context tools
    - Business tools (capability packs)
    - Audit tools
    - Resources (read-only context)
    - Permission enforcement
    - Audit logging
    """

    # MCP Protocol version
    PROTOCOL_VERSION = "2024-11-05"

    # Server info
    SERVER_NAME = "adapterly"
    SERVER_VERSION = "1.0.0"

    def __init__(
        self,
        account_id: int,
        api_key: str | None = None,
        mode: str = "safe",
        user_id: int | None = None,
        transport: str = "stdio",
        project_identifier: str | None = None,
        project_id: int | None = None,
    ):
        """
        Initialize MCP server.

        Args:
            account_id: Account ID for this session
            api_key: API key for authentication
            mode: Permission mode ("safe" or "power")
            user_id: Optional user ID
            transport: Transport type ("stdio" or "sse")
            project_identifier: Optional project identifier for category filtering
            project_id: Optional project DB ID for auto-resolving external identifiers
        """
        self.account_id = account_id
        self.api_key = api_key
        self.mode = mode
        self.user_id = user_id
        self.transport_type = transport
        self.project_identifier = project_identifier
        self.project_id = project_id

        # Generate session ID
        self.session_id = create_session_id()

        # Initialize components
        self.registry = MCPToolRegistry()
        self.permissions = get_permission_checker(account_id, api_key, mode, user_id=user_id)
        self.audit = MCPAuditLogger(
            account_id=account_id, session_id=self.session_id, user_id=user_id, transport=transport, mode=mode
        )
        self.session_manager = MCPSessionManager(account_id)

        # Resource providers
        self._system_resources = get_system_resources(account_id)

        # State
        self._initialized = False

    async def initialize(self):
        """Initialize the server and register tools."""
        from asgiref.sync import sync_to_async

        if self._initialized:
            return

        # Register context tools (required first)
        for tool in get_context_tools():
            self.registry.register(tool)

        # Register system tools (sync ORM call wrapped for async)
        try:
            system_tools = await sync_to_async(get_system_tools, thread_sensitive=False)(
                self.account_id, project_id=self.project_id
            )
            for tool in system_tools:
                self.registry.register(tool)
        except Exception as e:
            logger.warning(f"Failed to load system tools: {e}")

        # Register business tools from capability packs (sync ORM call wrapped for async)
        try:
            business_tools = await sync_to_async(get_business_tools, thread_sensitive=False)(self.account_id)
            for tool in business_tools:
                self.registry.register(tool)
            logger.info(f"Loaded {len(business_tools)} business tools from capability packs")
        except Exception as e:
            logger.warning(f"Failed to load business tools: {e}")

        # Register audit tools (reasoning and rollback)
        for tool in get_audit_tools():
            self.registry.register(tool)

        self._initialized = True
        logger.info(f"MCP Server initialized for account {self.account_id} with {len(self.registry)} tools")

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """
        Handle an incoming MCP message.

        Args:
            message: JSON-RPC message

        Returns:
            JSON-RPC response or None for notifications
        """
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        logger.debug(f"Handling MCP message: {method}")

        try:
            if method == "initialize":
                result = await self._handle_initialize(params)
            elif method == "initialized":
                # Notification - no response
                return None
            elif method == "tools/list":
                result = await self._handle_list_tools(params)
            elif method == "tools/call":
                result = await self._handle_call_tool(params)
            elif method == "resources/list":
                result = await self._handle_list_resources(params)
            elif method == "resources/read":
                result = await self._handle_read_resource(params)
            elif method == "ping":
                result = {}
            else:
                return self._error_response(msg_id, -32601, f"Method not found: {method}")

            return self._success_response(msg_id, result)

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return self._error_response(msg_id, -32603, str(e))

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        await self.initialize()

        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": True},
                "prompts": {"listChanged": False},
                "logging": {},
            },
        }

    async def _handle_list_tools(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request."""
        from asgiref.sync import sync_to_async

        filter_opts = self.permissions.get_tool_list_filter()
        # list_tools may trigger ORM calls (category resolver), wrap for async
        tools = await sync_to_async(self.registry.list_tools_mcp_format, thread_sensitive=False)(**filter_opts)

        return {"tools": tools}

    async def _handle_call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Tool name is required")

        # Get tool
        tool = self.registry.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Check permissions
        permission = self.permissions.can_call_tool(tool_name, tool.tool_type)
        if not permission.allowed:
            raise PermissionError(permission.reason)

        # Build context
        ctx = {
            "account_id": self.account_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "session_manager": self.session_manager,
            "audit": self.audit,
        }

        # Execute tool with audit logging
        with self.audit.timed_call(tool_name, tool.tool_type, arguments) as audit_ctx:
            result = await tool.handler(ctx, **arguments)
            audit_ctx.set_result(result)

        # Format response
        if isinstance(result, dict) and "error" in result:
            return {"content": [{"type": "text", "text": result["error"]}], "isError": True}

        return {"content": [{"type": "text", "text": self._format_result(result)}]}

    async def _handle_list_resources(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/list request."""
        resources = []

        # Collect from system resource provider
        resources.extend(await self._system_resources.list_resources())

        return {"resources": resources}

    async def _handle_read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")
        if not uri:
            raise ValueError("Resource URI is required")

        # Log resource access
        self.audit.log_tool_call(
            tool_name=f"resource:{uri}", tool_type="resource", parameters={"uri": uri}, result=None, duration_ms=0
        )

        # Route to appropriate provider
        if uri.startswith("systems://"):
            content = await self._system_resources.read_resource(uri)
        else:
            raise ValueError(f"Unknown resource URI: {uri}")

        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": self._format_result(content)}]}

    def _format_result(self, result: Any) -> str:
        """Format result as string."""
        import json

        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2, default=str)

    def _success_response(self, msg_id: Any, result: Any) -> dict[str, Any]:
        """Create success response."""
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _error_response(self, msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        """Create error response."""
        error = {"code": code, "message": message}
        if data:
            error["data"] = data

        return {"jsonrpc": "2.0", "id": msg_id, "error": error}

    async def close(self):
        """Close server and cleanup resources."""
        await self.session_manager.close_all()
        logger.info(f"MCP Server closed for session {self.session_id}")


async def run_stdio_server(
    account_id: int,
    api_key: str | None = None,
    mode: str = "safe",
    user_id: int | None = None,
    project_identifier: str | None = None,
):
    """
    Run MCP server with stdio transport.

    This is the main entry point for CLI usage.
    """
    from apps.mcp.transports.stdio import StdioTransport

    server = MCPServer(
        account_id=account_id,
        api_key=api_key,
        mode=mode,
        user_id=user_id,
        transport="stdio",
        project_identifier=project_identifier,
    )

    transport = StdioTransport(on_message=server.handle_message)

    try:
        await server.initialize()
        await transport.start()

        # Wait until transport stops
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        await transport.stop()
        await server.close()
