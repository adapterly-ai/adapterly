"""MCP JSON-RPC server – handles protocol messages."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.audit import AuditLog
from ..models.connection import Connection
from ..models.integration import Integration, Tool
from ..models.workspace import Workspace
from .permissions import PermissionChecker
from .session import MCPSession

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "adapterly"
SERVER_VERSION = "2.0.0"

_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "apikey", "credential", "auth"}


def _sanitize_params(params: dict) -> dict:
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


def _sanitize_tool_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_").lower()
    return name


async def handle_message(
    message: dict[str, Any],
    session: MCPSession,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Handle a single JSON-RPC message."""
    method = message.get("method")
    params = message.get("params", {})
    msg_id = message.get("id")

    try:
        if method == "initialize":
            result = _handle_initialize()
        elif method == "initialized":
            return None  # notification
        elif method == "tools/list":
            result = await _handle_list_tools(session, db)
        elif method == "tools/call":
            result = await _handle_call_tool(session, params, db)
        elif method == "ping":
            result = {}
        else:
            return _error(msg_id, -32601, f"Method not found: {method}")

        return _success(msg_id, result)

    except Exception as e:
        logger.error(f"Error handling {method}: {e}", exc_info=True)
        return _error(msg_id, -32603, str(e))


def _handle_initialize() -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"subscribe": False, "listChanged": False},
            "logging": {},
        },
    }


async def _handle_list_tools(session: MCPSession, db: AsyncSession) -> dict:
    """Build tool list from connections in the session's workspace."""
    tools = []
    checker = PermissionChecker(
        mode=session.mode,
        allowed_tools=session.allowed_tools,
        blocked_tools=session.blocked_tools,
    )

    # Admin keys get meta-tools
    if session.is_admin:
        from .meta_tools import META_TOOLS
        tools.extend(META_TOOLS)

    if not session.workspace_id:
        return {"tools": tools}

    # Get all active connections for this workspace
    result = await db.execute(
        select(Connection)
        .where(
            Connection.workspace_id == session.workspace_id,
            Connection.is_enabled == True,  # noqa: E712
        )
    )
    connections = result.scalars().all()

    if not connections:
        return {"tools": tools}

    integration_ids = [c.integration_id for c in connections]

    # Get integrations and their tools
    result = await db.execute(
        select(Integration)
        .options(selectinload(Integration.tools))
        .where(
            Integration.id.in_(integration_ids),
            Integration.is_active == True,  # noqa: E712
        )
    )
    integrations = result.scalars().all()

    for integration in integrations:
        for tool in integration.tools:
            if not tool.is_enabled:
                continue

            mcp_name = _sanitize_tool_name(f"{integration.slug}_{tool.slug}")
            tool_type = tool.tool_type or "read"

            if not checker.is_allowed(mcp_name, tool_type):
                continue

            description = tool.description or f"{tool.name} on {integration.name}"
            if tool.pagination:
                description += (
                    " (paginated: returns summary with count, columns and 3 sample items."
                    " Use 'page: N' for full page data, 'fetch_all_pages: true' to store all as dataset pointer)"
                )

            input_schema = dict(tool.parameters_schema) if tool.parameters_schema else {"type": "object", "properties": {}}
            if tool.pagination:
                props = dict(input_schema.get("properties", {}))
                props["page"] = {"type": "integer", "description": "Page number to fetch (0-indexed). Default: 0 (first page)."}
                props["fetch_all_pages"] = {"type": "boolean", "description": "Set to true to fetch ALL pages and return combined results.", "default": False}
                input_schema["properties"] = props

            tools.append({
                "name": mcp_name,
                "description": description,
                "inputSchema": input_schema,
            })

    return {"tools": tools}


async def _handle_call_tool(session: MCPSession, params: dict, db: AsyncSession) -> dict:
    """Execute a tool call."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    start = time.time()
    error_msg = None

    try:
        # Check plan tool call limit (skip for meta-tools, checked below)
        from ..billing.usage import check_tool_call_limit
        limit_error = await check_tool_call_limit(db, session.account_id)
        if limit_error:
            return {"content": [{"type": "text", "text": limit_error}], "isError": True}

        # Check if it's a meta-tool
        from .meta_tools import META_TOOLS, execute_meta_tool
        meta_names = {t["name"] for t in META_TOOLS}
        if tool_name in meta_names:
            if not session.is_admin:
                return {"content": [{"type": "text", "text": "Meta-tools require admin API key"}], "isError": True}
            result = await execute_meta_tool(tool_name, arguments, session, db)
            import json
            text = json.dumps(result, default=str)
            duration_ms = (time.time() - start) * 1000
            await _log_audit(db=db, session=session, tool_name=tool_name, params=arguments, duration_ms=duration_ms, success="error" not in result, error_message=result.get("error"))
            is_error = "error" in result
            return {"content": [{"type": "text", "text": text}], "isError": is_error}

        # Resolve tool from name
        tool, integration, connection = await _resolve_tool(tool_name, session, db)

        if not tool:
            error_msg = f"Tool not found: {tool_name}"
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Permission check
        checker = PermissionChecker(
            mode=session.mode,
            allowed_tools=session.allowed_tools,
            blocked_tools=session.blocked_tools,
        )
        if not checker.is_allowed(tool_name, tool.tool_type):
            error_msg = f"Tool not allowed: {tool_name} (mode={session.mode})"
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Execute via executor
        from ..executor.engine import execute_tool
        result = await execute_tool(
            tool=tool,
            integration=integration,
            connection=connection,
            params=arguments,
            db=db,
        )

        duration_ms = (time.time() - start) * 1000

        # Audit log
        await _log_audit(
            db=db,
            session=session,
            tool_name=tool_name,
            params=arguments,
            duration_ms=duration_ms,
            success="error" not in result,
            error_message=result.get("error"),
            status_code=result.get("status_code"),
        )

        if "error" in result:
            import json
            return {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "isError": True}

        import json
        text = json.dumps(result.get("data", result.get("dataset", result)), default=str)
        return {"content": [{"type": "text", "text": text}]}

    except Exception as e:
        logger.error(f"Tool call failed: {e}", exc_info=True)
        duration_ms = (time.time() - start) * 1000
        await _log_audit(
            db=db, session=session, tool_name=tool_name,
            params=arguments, duration_ms=duration_ms,
            success=False, error_message=str(e),
        )
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}


async def _resolve_tool(
    tool_name: str,
    session: MCPSession,
    db: AsyncSession,
) -> tuple[Tool | None, Integration | None, Connection | None]:
    """Resolve tool name → (Tool, Integration, Connection)."""
    if not session.workspace_id:
        return None, None, None

    # Get connections
    result = await db.execute(
        select(Connection).where(
            Connection.workspace_id == session.workspace_id,
            Connection.is_enabled == True,  # noqa: E712
        )
    )
    connections = result.scalars().all()
    connection_map = {c.integration_id: c for c in connections}

    result = await db.execute(
        select(Integration)
        .options(selectinload(Integration.tools))
        .where(
            Integration.id.in_(list(connection_map.keys())),
            Integration.is_active == True,  # noqa: E712
        )
    )
    integrations = result.scalars().all()

    for integration in integrations:
        for tool in integration.tools:
            mcp_name = _sanitize_tool_name(f"{integration.slug}_{tool.slug}")
            if mcp_name == tool_name:
                return tool, integration, connection_map[integration.id]

    return None, None, None


async def _log_audit(
    db: AsyncSession,
    session: MCPSession,
    tool_name: str,
    params: dict,
    duration_ms: float,
    success: bool,
    error_message: str | None = None,
    status_code: int | None = None,
):
    try:
        log = AuditLog(
            account_id=session.account_id,
            workspace_id=session.workspace_id,
            api_key_id=session.api_key_id,
            tool_name=tool_name,
            parameters=_sanitize_params(params),
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            status_code=status_code,
        )
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")


# JSON-RPC helpers

def _success(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}

def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
