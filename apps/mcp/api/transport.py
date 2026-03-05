"""
MCP Streamable HTTP Transport.

Implements the MCP Streamable HTTP transport specification.
Single endpoint that accepts JSON-RPC messages and returns responses
either as JSON or as SSE stream.

Usage:
    POST /api/mcp/
    Headers:
        - Authorization: Bearer <api_key>
        - Content-Type: application/json
        - Mcp-Session-Id: <session_id> (optional, returned by server)
        - Accept: application/json, text/event-stream
    Body:
        JSON-RPC message or batch

Response:
    - Content-Type: application/json (simple response)
    - Content-Type: text/event-stream (streaming response)
"""

import json
import logging
import time
import uuid
from typing import Any

from asgiref.sync import async_to_sync
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.mcp.models import MCPApiKey
from apps.mcp.server import MCPServer

logger = logging.getLogger(__name__)

# Active sessions store
_sessions: dict[str, dict[str, Any]] = {}

# Session timeout in seconds (30 minutes)
SESSION_TIMEOUT = 1800

# Session limits to prevent memory exhaustion
MAX_SESSIONS_PER_KEY = 10
MAX_TOTAL_SESSIONS = 1000


def _get_api_key_from_request(request) -> tuple[MCPApiKey | None, str | None]:
    """Extract and validate API key from request.

    Returns:
        Tuple of (MCPApiKey object, raw API key string)
    """
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
    else:
        key = request.GET.get("api_key", "")

    if not key:
        return None, None

    # Find API key by prefix
    prefix = key[:10] if len(key) >= 10 else key

    try:
        api_key = MCPApiKey.objects.select_related("account", "profile").get(key_prefix=prefix, is_active=True)

        if api_key.check_key(key):
            api_key.mark_used()
            return api_key, key
    except MCPApiKey.DoesNotExist:
        pass

    return None, None


def _cleanup_expired_sessions():
    """Remove expired sessions."""
    now = time.time()
    expired = [sid for sid, data in _sessions.items() if now - data.get("last_activity", 0) > SESSION_TIMEOUT]
    for sid in expired:
        logger.info(f"Cleaning up expired session: {sid}")
        _close_session(sid)


def _close_session(session_id: str):
    """Close and cleanup a session."""
    if session_id in _sessions:
        session = _sessions[session_id]
        server = session.get("server")
        if server:
            try:
                async_to_sync(server.close)()
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {e}")
        del _sessions[session_id]


def _get_or_create_session(request, api_key: MCPApiKey, api_key_string: str) -> tuple[str, dict[str, Any]]:
    """Get existing session or create new one."""
    session_id = request.headers.get("Mcp-Session-Id", "")

    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        session["last_activity"] = time.time()
        return session_id, session

    # Create new session — enforce limits
    if len(_sessions) >= MAX_TOTAL_SESSIONS:
        _cleanup_expired_sessions()
        if len(_sessions) >= MAX_TOTAL_SESSIONS:
            raise ValueError("Server session limit reached. Please try again later.")

    # Count sessions for this API key
    key_session_count = sum(1 for s in _sessions.values() if s.get("api_key_id") == api_key.id)
    if key_session_count >= MAX_SESSIONS_PER_KEY:
        _cleanup_expired_sessions()
        key_session_count = sum(1 for s in _sessions.values() if s.get("api_key_id") == api_key.id)
        if key_session_count >= MAX_SESSIONS_PER_KEY:
            raise ValueError("Too many active sessions for this API key. Close existing sessions first.")

    session_id = str(uuid.uuid4())

    # Determine mode from API key or profile
    if api_key.profile and api_key.profile.is_active:
        mode = api_key.profile.mode
    else:
        mode = api_key.mode

    # Create MCP server for this session
    # Pass the API key string so permission checker can look up categories
    # Pass project_id so system tools can auto-resolve external identifiers
    server = MCPServer(
        account_id=api_key.account.id,
        api_key=api_key_string,
        mode=mode,
        transport="http",
        project_id=api_key.project_id,
    )

    # Initialize server
    async_to_sync(server.initialize)()

    session = {
        "server": server,
        "account_id": api_key.account.id,
        "api_key_id": api_key.id,
        "mode": mode,
        "created_at": time.time(),
        "last_activity": time.time(),
    }

    _sessions[session_id] = session
    logger.info(f"Created new MCP session: {session_id} (account: {api_key.account.id})")

    return session_id, session


def _json_rpc_error(code: int, message: str, id=None, status=400) -> JsonResponse:
    """Return JSON-RPC error response."""
    return JsonResponse({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}, status=status)


@csrf_exempt
@require_http_methods(["POST", "GET", "DELETE"])
def mcp_endpoint(request):
    """
    MCP Streamable HTTP endpoint.

    POST: Send JSON-RPC message(s)
    GET: Open SSE stream for server-initiated messages (optional)
    DELETE: Close session

    Headers:
        Authorization: Bearer <api_key>
        Content-Type: application/json
        Accept: application/json, text/event-stream
        Mcp-Session-Id: <session_id> (optional)

    Returns:
        JSON-RPC response or SSE stream
    """
    # Cleanup expired sessions periodically
    _cleanup_expired_sessions()

    # Authenticate
    api_key, api_key_string = _get_api_key_from_request(request)
    if not api_key:
        base = request.build_absolute_uri("/")
        resp = _json_rpc_error(-32000, "Invalid or missing API key", status=401)
        resp["WWW-Authenticate"] = (
            f'Bearer resource_metadata="{base}.well-known/oauth-protected-resource/mcp/v1/"'
        )
        return resp

    # Handle DELETE (close session)
    if request.method == "DELETE":
        session_id = request.headers.get("Mcp-Session-Id", "")
        if session_id:
            _close_session(session_id)
            return HttpResponse(status=204)
        return HttpResponse(status=404)

    # Handle GET (SSE stream for server-initiated messages)
    if request.method == "GET":
        return _handle_sse_stream(request, api_key, api_key_string)

    # Handle POST (JSON-RPC messages)
    return _handle_post(request, api_key, api_key_string)


def _handle_post(request, api_key: MCPApiKey, api_key_string: str) -> HttpResponse:
    """Handle POST request with JSON-RPC message(s)."""
    # Parse request body
    try:
        body = json.loads(request.body) if request.body else None
    except json.JSONDecodeError:
        return _json_rpc_error(-32700, "Parse error")

    if not body:
        return _json_rpc_error(-32600, "Invalid request: empty body")

    # Get or create session
    try:
        session_id, session = _get_or_create_session(request, api_key, api_key_string)
    except ValueError as e:
        return _json_rpc_error(-32000, str(e), status=429)
    server = session["server"]

    # Check if client accepts SSE
    accept = request.headers.get("Accept", "")
    wants_sse = "text/event-stream" in accept

    # Handle batch or single message
    is_batch = isinstance(body, list)
    messages = body if is_batch else [body]

    # Process messages
    responses = []
    for message in messages:
        try:
            response = async_to_sync(server.handle_message)(message)
            if response:
                responses.append(response)
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id") if isinstance(message, dict) else None,
                    "error": {"code": -32603, "message": str(e)},
                }
            )

    # Return response
    if wants_sse and responses:
        # Return as SSE stream
        return _sse_response(session_id, responses)

    # Return as JSON
    if is_batch:
        result = responses
    elif responses:
        result = responses[0]
    else:
        # No response (notification)
        return HttpResponse(status=202)

    response = JsonResponse(result, safe=False)
    response["Mcp-Session-Id"] = session_id
    return response


def _sse_response(session_id: str, messages: list) -> StreamingHttpResponse:
    """Return messages as SSE stream."""

    def event_stream():
        for msg in messages:
            yield f"data: {json.dumps(msg)}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["Mcp-Session-Id"] = session_id
    return response


def _handle_sse_stream(request, api_key: MCPApiKey, api_key_string: str) -> StreamingHttpResponse:
    """
    Handle GET request for SSE stream.

    This is used for server-initiated messages (notifications, progress, etc.)
    """
    try:
        session_id, session = _get_or_create_session(request, api_key, api_key_string)
    except ValueError as e:
        return _json_rpc_error(-32000, str(e), status=429)

    def event_stream():
        """Generate SSE events."""
        # Send session info
        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

        # Send endpoint info for MCP protocol
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
        while session_id in _sessions:
            # Check if session still active
            if time.time() - _sessions[session_id].get("last_activity", 0) > SESSION_TIMEOUT:
                break

            # Send keepalive every 15 seconds
            if time.time() - last_ping > 15:
                yield ": keepalive\n\n"
                last_ping = time.time()

            time.sleep(0.5)

        # Session ended
        yield f"event: close\ndata: {json.dumps({'reason': 'session_ended'})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["Mcp-Session-Id"] = session_id
    return response


def get_active_sessions() -> list:
    """Get list of active sessions (for admin/debugging)."""
    return [
        {
            "session_id": sid,
            "account_id": data.get("account_id"),
            "api_key_id": data.get("api_key_id"),
            "mode": data.get("mode"),
            "created_at": data.get("created_at"),
            "last_activity": data.get("last_activity"),
        }
        for sid, data in _sessions.items()
    ]
