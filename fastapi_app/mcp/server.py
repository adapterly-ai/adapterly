"""
MCP Server - async implementation for FastAPI.

This is the core component that:
- Handles MCP protocol messages
- Manages tool and resource registration
- Enforces permissions (Safe/Power mode)
- Manages project-based access control via ProjectIntegration
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.mcp import MCPAuditLog, Project
from .permissions import MCPPermissionChecker
from .tools import get_all_tools

logger = logging.getLogger(__name__)


_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "apikey", "credential", "auth"}


def _sanitize_params(params: dict) -> dict:
    """Remove sensitive values from parameters for audit logging."""
    if not isinstance(params, dict):
        return {}
    sanitized = {}
    for key, value in params.items():
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            sanitized[key] = "***"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_params(value)
        else:
            sanitized[key] = value
    return sanitized


class MCPServer:
    """
    Adapterly MCP Server (FastAPI async version).

    Provides MCP protocol implementation with:
    - System tools (scoped by ProjectIntegration)
    - Resources
    - Permission enforcement
    """

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "adapterly"
    SERVER_VERSION = "1.0.0"

    def __init__(
        self,
        account_id: int,
        api_key: str | None = None,
        api_key_id: int | None = None,
        is_admin: bool = False,
        mode: str = "safe",
        user_id: int | None = None,
        transport: str = "http",
        project: Project | None = None,
        db: AsyncSession | None = None,
    ):
        """
        Initialize MCP server.

        Args:
            account_id: Account ID for this session
            api_key: API key string
            api_key_id: API key database ID
            is_admin: Whether this is an admin token
            mode: Permission mode ("safe" or "power")
            user_id: Optional user ID
            transport: Transport type ("stdio" or "http")
            project: Project for scoped access (required for non-admin)
            db: Database session
        """
        self.account_id = account_id
        self.api_key = api_key
        self.api_key_id = api_key_id
        self.is_admin = is_admin
        self.mode = mode
        self.user_id = user_id
        self.transport_type = transport
        self.project = project
        self.project_id = project.id if project else None
        self.project_slug = project.slug if project else None
        self.db = db

        # Session ID
        self.session_id = str(uuid.uuid4())

        # Tool registry
        self._tools: dict[str, Any] = {}

        # Permission checker
        self.permissions: MCPPermissionChecker | None = None

        # State
        self._initialized = False

    async def initialize(self):
        """Initialize the server and register tools."""
        if self._initialized:
            return

        # Initialize permission checker with project context
        self.permissions = await MCPPermissionChecker.create(
            account_id=self.account_id,
            api_key_id=self.api_key_id,
            is_admin=self.is_admin,
            mode=self.mode,
            project=self.project,
            user_id=self.user_id,
            db=self.db,
        )

        # Load all tools (project-scoped via ProjectIntegration)
        project_id = self.project_id
        tools = await get_all_tools(self.account_id, self.db, project_id=project_id)
        for tool in tools:
            self._tools[tool["name"]] = tool

        self._initialized = True
        project_info = f", project={self.project_slug}" if self.project else ""
        logger.info(f"MCP Server initialized for account {self.account_id}{project_info} with {len(self._tools)} tools")

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
        # Filter tools based on permissions
        allowed_tools = []

        for name, tool in self._tools.items():
            if self.permissions.is_tool_allowed(name, tool.get("tool_type", "system_read")):
                allowed_tools.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "inputSchema": tool.get("input_schema", {"type": "object"}),
                    }
                )

        logger.info(f"Returning {len(allowed_tools)} tools for account {self.account_id}")
        return {"tools": allowed_tools}

    async def _handle_call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Tool name is required")

        # Get tool
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Check permissions
        tool_type = tool.get("tool_type", "system_read")
        if not self.permissions.is_tool_allowed(tool_name, tool_type):
            raise PermissionError(f"Tool '{tool_name}' is not allowed")

        # Execute tool
        handler = tool.get("handler")
        if not handler:
            raise ValueError(f"Tool '{tool_name}' has no handler")

        # Build context — project is always set for non-admin tokens
        ctx = {
            "account_id": self.account_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "db": self.db,
            "project": self.project,
            "project_id": self.project_id,
        }

        start_time = time.time()
        success = True
        error_message = ""
        result = None

        try:
            result = await handler(ctx, **arguments)

            # Check if result indicates an error
            if isinstance(result, dict) and "error" in result:
                success = False
                error_message = result["error"]
        except Exception as e:
            success = False
            error_message = str(e)
            raise
        finally:
            # Log to MCPAuditLog
            duration_ms = int((time.time() - start_time) * 1000)
            await self._log_tool_call(
                tool_name=tool_name,
                tool_type=tool_type,
                parameters=arguments,
                result=result,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
            )

        # Format response
        if isinstance(result, dict) and "error" in result:
            error_text = result["error"]
            if diagnostic := result.get("diagnostic"):
                error_text += "\n\n--- Diagnosis ---"
                error_text += f"\nCategory: {diagnostic['category']}"
                error_text += f"\nDiagnosis: {diagnostic['summary']}"
                if diagnostic.get("has_fix"):
                    error_text += f"\nSuggested fix: {diagnostic['fix_description']}"
                    error_text += f"\n(Diagnostic ID: {diagnostic['id']} — use get_diagnostics tool for details)"
            return {"content": [{"type": "text", "text": error_text}], "isError": True}

        # Build response content
        content = [{"type": "text", "text": self._format_result(result)}]

        return {"content": content}

    async def _log_tool_call(
        self,
        tool_name: str,
        tool_type: str,
        parameters: dict,
        result: Any,
        duration_ms: int,
        success: bool,
        error_message: str,
    ) -> None:
        """Log a tool call to MCPAuditLog."""
        try:
            # Sanitize parameters - remove sensitive fields
            sanitized_params = _sanitize_params(parameters)

            # Build result summary (truncated)
            result_summary = {}
            if isinstance(result, dict):
                result_summary["success"] = result.get("success")
                result_summary["status_code"] = result.get("status_code")
                if "data" in result:
                    data = result["data"]
                    if isinstance(data, list):
                        result_summary["item_count"] = len(data)
                    elif isinstance(data, dict):
                        result_summary["keys"] = list(data.keys())[:10]

            audit_log = MCPAuditLog(
                account_id=self.account_id,
                user_id=self.user_id,
                tool_name=tool_name,
                tool_type=tool_type,
                parameters=sanitized_params,
                result_summary=result_summary,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message[:2000] if error_message else "",
                session_id=self.session_id,
                transport=self.transport_type,
                mode=self.mode,
                timestamp=datetime.utcnow(),
            )
            self.db.add(audit_log)
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to log audit entry (non-fatal): {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

    async def _handle_list_resources(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/list request."""
        # TODO: Implement resource listing
        return {"resources": []}

    async def _handle_read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")
        if not uri:
            raise ValueError("Resource URI is required")

        # TODO: Implement resource reading
        raise ValueError(f"Unknown resource URI: {uri}")

    def _format_result(self, result: Any) -> str:
        """Format result as string."""
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
        logger.info(f"MCP Server closed for session {self.session_id}")
