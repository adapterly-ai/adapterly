"""
MCP Streamable HTTP transport for the standalone gateway.

Implements JSON-RPC 2.0 over HTTP (POST /mcp/v1/) so that Claude Code
and other MCP clients can connect directly to the gateway.

Reuses gateway_core for auth, tool listing, and execution.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_core.auth import validate_api_key
from gateway_core.executor import execute_system_tool, get_system_tools
from gateway_core.models import MCPApiKey, MCPAuditLog, Project

from .database import get_db

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "adapterly-gateway"
SERVER_VERSION = "0.1.0"

_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "apikey", "credential", "auth"}

mcp_router = APIRouter(prefix="/mcp/v1", tags=["MCP Streamable HTTP"])


# ---------------------------------------------------------------------------
# Session management (in-memory, TTL-based)
# ---------------------------------------------------------------------------


@dataclass
class MCPSession:
    id: str
    account_id: int
    api_key_id: int
    api_key_obj: MCPApiKey
    project: Project | None
    mode: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_active: bool = True

    def touch(self):
        self.last_activity = time.time()


class SessionManager:
    SESSION_TIMEOUT = 1800  # 30 minutes

    def __init__(self):
        self._sessions: dict[str, MCPSession] = {}

    def cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_activity > self.SESSION_TIMEOUT]
        for sid in expired:
            self._sessions[sid].is_active = False
            del self._sessions[sid]

    async def get_or_create(
        self,
        session_id: str | None,
        api_key: MCPApiKey,
        project: Project | None,
        db: AsyncSession,
    ) -> MCPSession:
        self.cleanup_expired()

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.touch()
            return session

        # Load tools
        project_id = project.id if project else None
        tools = await get_system_tools(db, api_key.account_id, project_id=project_id)

        new_id = str(uuid.uuid4())
        session = MCPSession(
            id=new_id,
            account_id=api_key.account_id,
            api_key_id=api_key.id,
            api_key_obj=api_key,
            project=project,
            mode=api_key.mode or "safe",
            tools=tools,
        )
        self._sessions[new_id] = session
        logger.info(
            "New MCP session %s: account=%d, project=%s, tools=%d",
            new_id[:8],
            api_key.account_id,
            project.slug if project else "admin",
            len(tools),
        )
        return session

    async def close(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id].is_active = False
            del self._sessions[session_id]


_sessions = SessionManager()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


async def _authenticate(authorization: str | None, db: AsyncSession) -> tuple[MCPApiKey, Project | None, str]:
    """Validate Bearer token, return (api_key, project, raw_key)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise ValueError("Missing or invalid Authorization header")
    raw_key = authorization[7:]
    api_key, project = await validate_api_key(raw_key, db)
    return api_key, project, raw_key


# ---------------------------------------------------------------------------
# Permission check (lightweight — matches monolith logic)
# ---------------------------------------------------------------------------


def _is_tool_allowed(tool: dict[str, Any], api_key: MCPApiKey) -> bool:
    """Check if a tool is allowed by the API key's mode and allowed/blocked lists."""
    tool_name = tool["name"]
    tool_type = tool.get("tool_type", "system_read")

    # Mode check: safe mode blocks write tools
    if (api_key.mode or "safe") == "safe" and tool_type == "system_write":
        return False

    # Allowed list (whitelist): if set, only these tools are allowed
    allowed = api_key.allowed_tools or []
    if allowed and tool_name not in allowed:
        return False

    # Blocked list (blacklist)
    blocked = api_key.blocked_tools or []
    if tool_name in blocked:
        return False

    return True


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _success(msg_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


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


def _format_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------


async def _handle_message(
    message: dict[str, Any],
    session: MCPSession,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Dispatch a single JSON-RPC message."""
    method = message.get("method")
    params = message.get("params", {})
    msg_id = message.get("id")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": False, "listChanged": True},
                    "prompts": {"listChanged": False},
                    "logging": {},
                },
            }
            return _success(msg_id, result)

        if method == "initialized":
            return None  # notification

        if method == "ping":
            return _success(msg_id, {})

        if method == "tools/list":
            allowed = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": t.get("input_schema", {"type": "object"}),
                }
                for t in session.tools
                if _is_tool_allowed(t, session.api_key_obj)
            ]
            return _success(msg_id, {"tools": allowed})

        if method == "tools/call":
            return await _handle_tool_call(msg_id, params, session, db)

        if method == "resources/list":
            return _success(msg_id, {"resources": []})

        return _error(msg_id, -32601, f"Method not found: {method}")

    except Exception as e:
        logger.error("Error handling %s: %s", method, e, exc_info=True)
        return _error(msg_id, -32603, str(e))


async def _handle_tool_call(
    msg_id: Any,
    params: dict[str, Any],
    session: MCPSession,
    db: AsyncSession,
) -> dict[str, Any]:
    """Execute a tool call and return the JSON-RPC response."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not tool_name:
        return _error(msg_id, -32602, "Missing tool name in params")

    # Find tool definition
    tool_def = next((t for t in session.tools if t["name"] == tool_name), None)
    if not tool_def:
        return _error(msg_id, -32602, f"Unknown tool: {tool_name}")

    # Permission check
    if not _is_tool_allowed(tool_def, session.api_key_obj):
        return _error(msg_id, -32602, f"Tool '{tool_name}' is not allowed")

    project_id = session.project.id if session.project else None
    start_time = time.time()
    success = True
    error_message = ""
    result = None

    try:
        result = await execute_system_tool(
            db=db,
            action_id=tool_def["action_id"],
            account_id=session.account_id,
            params=arguments,
            project_id=project_id,
            store_datasets=False,
        )

        if isinstance(result, dict) and "error" in result:
            success = False
            error_message = result["error"]

    except Exception as e:
        success = False
        error_message = str(e)
        result = {"error": str(e)}

    # Audit log
    duration_ms = int((time.time() - start_time) * 1000)
    try:
        audit = MCPAuditLog(
            account_id=session.account_id,
            tool_name=tool_name,
            tool_type=tool_def.get("tool_type", "system_read"),
            parameters=_sanitize_params(arguments),
            result_summary=_build_result_summary(result),
            duration_ms=duration_ms,
            success=success,
            error_message=(error_message[:2000] if error_message else ""),
            session_id=session.id,
            transport="http",
            mode=session.mode,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(audit)
        await db.commit()
    except Exception as e:
        logger.warning("Audit log failed (non-fatal): %s", e)
        try:
            await db.rollback()
        except Exception:
            pass

    # Build MCP response content
    if isinstance(result, dict) and "error" in result:
        error_text = result["error"]
        if diagnostic := result.get("diagnostic"):
            error_text += "\n\n--- Diagnosis ---"
            error_text += f"\nCategory: {diagnostic['category']}"
            error_text += f"\nDiagnosis: {diagnostic['summary']}"
            if diagnostic.get("has_fix"):
                error_text += f"\nSuggested fix: {diagnostic['fix_description']}"
        return _success(msg_id, {"content": [{"type": "text", "text": error_text}], "isError": True})

    return _success(msg_id, {"content": [{"type": "text", "text": _format_result(result)}]})


def _build_result_summary(result: Any) -> dict:
    summary: dict[str, Any] = {}
    if isinstance(result, dict):
        summary["success"] = result.get("success")
        summary["status_code"] = result.get("status_code")
        if "data" in result:
            data = result["data"]
            if isinstance(data, list):
                summary["item_count"] = len(data)
            elif isinstance(data, dict):
                summary["keys"] = list(data.keys())[:10]
    return summary


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


@mcp_router.post("/")
async def mcp_post(
    request: Request,
    authorization: str | None = Header(None),
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    db: AsyncSession = Depends(get_db),
):
    """
    MCP Streamable HTTP endpoint — JSON-RPC 2.0.

    POST /mcp/v1/
    Headers: Authorization: Bearer <api_key>
    Body: JSON-RPC message or batch
    """
    # Auth
    try:
        api_key, project, raw_key = await _authenticate(authorization, db)
    except ValueError as e:
        return JSONResponse(
            content=_error(None, -32000, str(e)),
            status_code=401,
        )

    # Parse body
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(content=_error(None, -32700, "Parse error"), status_code=400)

    if not body:
        return JSONResponse(content=_error(None, -32600, "Empty body"), status_code=400)

    # Session
    session = await _sessions.get_or_create(
        session_id=mcp_session_id,
        api_key=api_key,
        project=project,
        db=db,
    )

    # Handle batch or single
    is_batch = isinstance(body, list)
    messages = body if is_batch else [body]

    responses = []
    for message in messages:
        try:
            resp = await _handle_message(message, session, db)
            if resp is not None:
                responses.append(resp)
        except Exception as e:
            logger.error("Unhandled error: %s", e, exc_info=True)
            responses.append(
                _error(
                    message.get("id") if isinstance(message, dict) else None,
                    -32603,
                    str(e),
                )
            )

    # SSE support
    accept = request.headers.get("Accept", "")
    if "text/event-stream" in accept and responses:
        return _sse_response(session.id, responses)

    # JSON response
    if is_batch:
        result = responses
    elif responses:
        result = responses[0]
    else:
        return Response(status_code=202, headers={"Mcp-Session-Id": session.id})

    return JSONResponse(content=result, headers={"Mcp-Session-Id": session.id})


@mcp_router.get("/")
async def mcp_get(
    request: Request,
    authorization: str | None = Header(None),
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream for server-initiated messages."""
    try:
        api_key, project, raw_key = await _authenticate(authorization, db)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=401)

    session = await _sessions.get_or_create(
        session_id=mcp_session_id,
        api_key=api_key,
        project=project,
        db=db,
    )

    import asyncio

    async def event_stream():
        yield f"event: session\ndata: {json.dumps({'session_id': session.id})}\n\n"
        endpoint_event = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
        yield f"data: {json.dumps(endpoint_event)}\n\n"

        last_ping = time.time()
        while session.is_active:
            if time.time() - last_ping > 15:
                yield ": keepalive\n\n"
                last_ping = time.time()
            await asyncio.sleep(0.5)

        yield f"event: close\ndata: {json.dumps({'reason': 'session_ended'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Mcp-Session-Id": session.id,
        },
    )


@mcp_router.delete("/")
async def mcp_delete(
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Close MCP session."""
    if mcp_session_id:
        await _sessions.close(mcp_session_id)
        return Response(status_code=204)
    return Response(status_code=404)


def _sse_response(session_id: str, messages: list) -> StreamingResponse:
    async def event_stream():
        for msg in messages:
            yield f"data: {json.dumps(msg)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Mcp-Session-Id": session_id,
        },
    )
