"""MCP Streamable HTTP transport router."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.api_key import APIKey
from ..models.workspace import Workspace
from ..api.deps import get_api_key, get_api_key_with_workspace
from .server import handle_message
from .session import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/v1", tags=["MCP"])

session_manager = SessionManager()


def json_rpc_error(code: int, message: str, id: Any = None) -> JSONResponse:
    return JSONResponse(
        content={"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}},
        status_code=400,
    )


@router.post("/")
async def mcp_post(
    request: Request,
    auth_result: tuple[APIKey, Workspace | None] = Depends(get_api_key_with_workspace),
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    db: AsyncSession = Depends(get_db),
):
    api_key, workspace = auth_result

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return json_rpc_error(-32700, "Parse error")

    if not body:
        return json_rpc_error(-32600, "Invalid request: empty body")

    session = session_manager.get_or_create(
        session_id=mcp_session_id,
        api_key=api_key,
        workspace=workspace,
    )

    is_batch = isinstance(body, list)
    messages = body if is_batch else [body]

    responses = []
    for message in messages:
        try:
            response = await handle_message(message, session, db)
            if response:
                responses.append(response)
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            responses.append({
                "jsonrpc": "2.0",
                "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32603, "message": str(e)},
            })

    if is_batch:
        result = responses
    elif responses:
        result = responses[0]
    else:
        return Response(status_code=202)

    return JSONResponse(content=result, headers={"Mcp-Session-Id": session.id})


@router.get("/")
async def mcp_get(
    request: Request,
    auth_result: tuple[APIKey, Workspace | None] = Depends(get_api_key_with_workspace),
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream for server-initiated notifications."""
    api_key, workspace = auth_result
    session = session_manager.get_or_create(
        session_id=mcp_session_id, api_key=api_key, workspace=workspace,
    )

    async def event_stream():
        import asyncio
        yield f"event: session\ndata: {json.dumps({'session_id': session.id})}\n\n"

        last_ping = time.time()
        while session.is_active:
            # Drain notifications
            for notif in session.drain_notifications():
                yield f"data: {json.dumps(notif)}\n\n"

            if time.time() - last_ping > 15:
                yield ": keepalive\n\n"
                last_ping = time.time()

            await asyncio.sleep(0.5)

        yield f"event: close\ndata: {json.dumps({'reason': 'session_ended'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Mcp-Session-Id": session.id},
    )


@router.delete("/")
async def mcp_delete(
    mcp_session_id: str | None = Header(None, alias="Mcp-Session-Id"),
    api_key: APIKey = Depends(get_api_key),
):
    if mcp_session_id:
        session_manager.close(mcp_session_id)
        return Response(status_code=204)
    return Response(status_code=404)
