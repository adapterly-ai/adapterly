"""
REST API for tool listing and execution.

Provides a simple REST interface alongside MCP JSON-RPC:
  GET  /api/v1/tools/              → list available tools
  POST /api/v1/tools/<name>/call   → call a tool with parameters

Uses the same MCPServer pipeline (auth, permissions, audit, executor)
so results are identical to MCP protocol calls.
"""

import json
import logging

from asgiref.sync import async_to_sync
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.mcp.api.transport import _get_api_key_from_request
from apps.mcp.server import MCPServer

logger = logging.getLogger(__name__)


def _auth_required(view_func):
    """Decorator: authenticate via Bearer API key."""

    def wrapper(request, *args, **kwargs):
        api_key, api_key_string = _get_api_key_from_request(request)
        if not api_key:
            return JsonResponse({"error": "Invalid or missing API key."}, status=401)
        request.api_key = api_key
        request.api_key_string = api_key_string
        return view_func(request, *args, **kwargs)

    return wrapper


def _create_server(api_key, api_key_string):
    """Create and initialize an MCPServer for a single request."""
    if api_key.profile and api_key.profile.is_active:
        mode = api_key.profile.mode
    else:
        mode = api_key.mode

    server = MCPServer(
        account_id=api_key.account.id,
        api_key=api_key_string,
        mode=mode,
        transport="http",
        project_id=api_key.project_id,
    )
    async_to_sync(server.initialize)()
    return server


@csrf_exempt
@require_GET
@_auth_required
def list_tools(request):
    """
    GET /api/v1/tools/

    Returns available tools for the authenticated API key.
    Query params:
      - format: "simple" (default) or "mcp" (full MCP schema)
      - search: filter tools by name substring
    """
    server = _create_server(request.api_key, request.api_key_string)

    try:
        result = async_to_sync(server._handle_list_tools)({})
    finally:
        async_to_sync(server.close)()

    tools = result.get("tools", [])

    # Optional search filter
    search = request.GET.get("search", "").lower()
    if search:
        tools = [t for t in tools if search in t["name"].lower() or search in t.get("description", "").lower()]

    fmt = request.GET.get("format", "simple")
    if fmt == "simple":
        tools = [{"name": t["name"], "description": t.get("description", "")} for t in tools]

    return JsonResponse({"tools": tools, "count": len(tools)})


@csrf_exempt
@require_POST
@_auth_required
def call_tool(request, tool_name):
    """
    POST /api/v1/tools/<tool_name>/call

    Call a tool with the given parameters.
    Body: JSON object with tool parameters.

    Returns:
      {"success": true, "data": ...} or {"success": false, "error": "..."}
    """
    # Parse body
    try:
        if request.body:
            arguments = json.loads(request.body)
        else:
            arguments = {}
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON body."}, status=400)

    if not isinstance(arguments, dict):
        return JsonResponse({"success": False, "error": "Body must be a JSON object."}, status=400)

    server = _create_server(request.api_key, request.api_key_string)

    try:
        result = async_to_sync(server._handle_call_tool)({"name": tool_name, "arguments": arguments})
    except PermissionError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=404)
    except Exception as e:
        logger.error("Tool call error: %s", e, exc_info=True)
        return JsonResponse({"success": False, "error": str(e)}, status=500)
    finally:
        async_to_sync(server.close)()

    # Extract content from MCP response format
    content = result.get("content", [])
    is_error = result.get("isError", False)

    # Parse the text content back to structured data if possible
    text = content[0]["text"] if content else ""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        data = text

    if is_error:
        return JsonResponse({"success": False, "error": data}, status=400)

    return JsonResponse({"success": True, "data": data})
