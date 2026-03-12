"""
MCP Streamable HTTP Transport router.

Implements the MCP Streamable HTTP transport specification.
Single endpoint that accepts JSON-RPC messages and returns responses.
"""

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import get_api_key, get_api_key_string, get_api_key_with_project
from ..models.mcp import MCPApiKey, Project
from .server import MCPServer
from .sessions import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/v1", tags=["MCP"])

# Session manager (in-memory for now)
session_manager = SessionManager()


def json_rpc_error(code: int, message: str, id: Any = None, status_code: int = 400) -> JSONResponse:
    """Return JSON-RPC error response."""
    return JSONResponse(
        content={"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}, status_code=status_code
    )


@router.post("/")
async def mcp_post(
    request: Request,
    auth_result: tuple[MCPApiKey, Project | None] = Depends(get_api_key_with_project),
    api_key_string: str = Depends(get_api_key_string),
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle MCP JSON-RPC messages.

    POST /mcp/v1/
    Headers:
        Authorization: Bearer <api_key>
        Content-Type: application/json
        Mcp-Session-Id: <session_id> (optional)

    Body:
        JSON-RPC message or batch

    Returns:
        JSON-RPC response with Mcp-Session-Id header
    """
    api_key, project = auth_result

    # Parse request body
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return json_rpc_error(-32700, "Parse error")

    if not body:
        return json_rpc_error(-32600, "Invalid request: empty body")

    # Get or create session with project context
    session = await session_manager.get_or_create(
        session_id=mcp_session_id, api_key=api_key, api_key_string=api_key_string, db=db, project=project
    )

    # Handle batch or single message
    is_batch = isinstance(body, list)
    messages = body if is_batch else [body]

    # Process messages
    responses = []
    for message in messages:
        try:
            response = await session.server.handle_message(message)
            if response:
                responses.append(response)
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id") if isinstance(message, dict) else None,
                    "error": {"code": -32603, "message": str(e)},
                }
            )

    # Check if client accepts SSE
    accept = request.headers.get("Accept", "")
    wants_sse = "text/event-stream" in accept

    if wants_sse and responses:
        # Return as SSE stream
        return sse_response(session.id, responses)

    # Return as JSON
    if is_batch:
        result = responses
    elif responses:
        result = responses[0]
    else:
        # No response (notification)
        return Response(status_code=202)

    return JSONResponse(content=result, headers={"Mcp-Session-Id": session.id})


@router.get("/")
async def mcp_get(
    request: Request,
    auth_result: tuple[MCPApiKey, Project | None] = Depends(get_api_key_with_project),
    api_key_string: str = Depends(get_api_key_string),
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    db: AsyncSession = Depends(get_db),
):
    """
    Open SSE stream for server-initiated messages.

    GET /mcp/v1/
    Headers:
        Authorization: Bearer <api_key>
        Accept: text/event-stream
        Mcp-Session-Id: <session_id> (optional)

    Returns:
        SSE stream
    """
    api_key, project = auth_result

    # Get or create session with project context
    session = await session_manager.get_or_create(
        session_id=mcp_session_id, api_key=api_key, api_key_string=api_key_string, db=db, project=project
    )

    async def event_stream():
        """Generate SSE events."""
        # Send session info
        yield f"event: session\ndata: {json.dumps({'session_id': session.id})}\n\n"

        # Send endpoint info
        endpoint_event = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {
                "protocolVersion": MCPServer.PROTOCOL_VERSION,
                "serverInfo": {"name": MCPServer.SERVER_NAME, "version": MCPServer.SERVER_VERSION},
            },
        }
        yield f"data: {json.dumps(endpoint_event)}\n\n"

        # Keep connection alive
        last_ping = time.time()
        while session.is_active:
            # Send keepalive every 15 seconds
            if time.time() - last_ping > 15:
                yield ": keepalive\n\n"
                last_ping = time.time()

            # Small sleep to prevent CPU spin
            import asyncio

            await asyncio.sleep(0.5)

        # Session ended
        yield f"event: close\ndata: {json.dumps({'reason': 'session_ended'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Mcp-Session-Id": session.id},
    )


@router.delete("/")
async def mcp_delete(
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    api_key: MCPApiKey = Depends(get_api_key),
):
    """
    Close MCP session.

    DELETE /mcp/v1/
    Headers:
        Authorization: Bearer <api_key>
        Mcp-Session-Id: <session_id>

    Returns:
        204 No Content
    """
    if mcp_session_id:
        await session_manager.close(mcp_session_id)
        return Response(status_code=204)

    return Response(status_code=404)


def sse_response(session_id: str, messages: list) -> StreamingResponse:
    """Return messages as SSE stream."""

    async def event_stream():
        for msg in messages:
            yield f"data: {json.dumps(msg)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Mcp-Session-Id": session_id},
    )
