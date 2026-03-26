"""Tests for the MCP JSON-RPC endpoint at /mcp/v1/."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from adapterly.models import Integration


# ── helpers ───────────────────────────────────────────────────────────────

def _rpc(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request."""
    msg = {"jsonrpc": "2.0", "method": method, "id": msg_id}
    if params is not None:
        msg["params"] = params
    return msg


# ── initialize ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_initialize(client: AsyncClient):
    resp = await client.post("/mcp/v1/", json=_rpc("initialize"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "adapterly"
    assert result["serverInfo"]["version"] == "2.0.0"
    assert "tools" in result["capabilities"]


@pytest.mark.asyncio
async def test_mcp_initialize_returns_session_header(client: AsyncClient):
    resp = await client.post("/mcp/v1/", json=_rpc("initialize"))
    assert "mcp-session-id" in resp.headers


# ── tools/list ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_tools_list_admin_gets_meta_tools(client: AsyncClient):
    """Admin key should see meta-tools (integration_list, workspace_list, etc.)."""
    resp = await client.post("/mcp/v1/", json=_rpc("tools/list"))
    assert resp.status_code == 200
    body = resp.json()
    tools = body["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "integration_list" in tool_names
    assert "workspace_list" in tool_names
    assert "workspace_create" in tool_names
    assert "connection_create" in tool_names


@pytest.mark.asyncio
async def test_mcp_tools_list_includes_inputschema(client: AsyncClient):
    resp = await client.post("/mcp/v1/", json=_rpc("tools/list"))
    body = resp.json()
    tools = body["result"]["tools"]
    for tool in tools:
        assert "inputSchema" in tool
        assert "name" in tool
        assert "description" in tool


# ── tools/call: integration_list ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_call_integration_list_empty(client: AsyncClient):
    """Calling integration_list when no integrations exist."""
    resp = await client.post(
        "/mcp/v1/",
        json=_rpc("tools/call", {"name": "integration_list", "arguments": {}}),
    )
    assert resp.status_code == 200
    body = resp.json()
    result = body["result"]
    content_text = result["content"][0]["text"]
    data = json.loads(content_text)
    assert "integrations" in data
    assert isinstance(data["integrations"], list)


@pytest.mark.asyncio
async def test_mcp_call_integration_list_with_data(
    client: AsyncClient,
    test_integration: Integration,
):
    """integration_list should return created integration."""
    resp = await client.post(
        "/mcp/v1/",
        json=_rpc("tools/call", {"name": "integration_list", "arguments": {}}),
    )
    body = resp.json()
    content_text = body["result"]["content"][0]["text"]
    data = json.loads(content_text)
    slugs = [i["slug"] for i in data["integrations"]]
    assert "test-api" in slugs


# ── tools/call: workspace_list ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_call_workspace_list(client: AsyncClient, test_workspace):
    resp = await client.post(
        "/mcp/v1/",
        json=_rpc("tools/call", {"name": "workspace_list", "arguments": {}}),
    )
    body = resp.json()
    content_text = body["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert "workspaces" in data
    slugs = [w["slug"] for w in data["workspaces"]]
    assert "default" in slugs


# ── ping ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_ping(client: AsyncClient):
    resp = await client.post("/mcp/v1/", json=_rpc("ping"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == {}


# ── unknown method ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_unknown_method(client: AsyncClient):
    resp = await client.post("/mcp/v1/", json=_rpc("nonexistent/method"))
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == -32601


# ── initialized (notification, no response) ──────────────────────────────

@pytest.mark.asyncio
async def test_mcp_initialized_notification(client: AsyncClient):
    """'initialized' is a notification – server returns 202 (no id response)."""
    resp = await client.post(
        "/mcp/v1/",
        json={"jsonrpc": "2.0", "method": "initialized"},
    )
    # initialized has no id so handle_message returns None → 202
    assert resp.status_code == 202


# ── batch request ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_batch_request(client: AsyncClient):
    batch = [
        _rpc("ping", msg_id=10),
        _rpc("initialize", msg_id=11),
    ]
    resp = await client.post("/mcp/v1/", json=batch)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    ids = {item["id"] for item in body}
    assert ids == {10, 11}


# ── malformed JSON ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_empty_body(client: AsyncClient):
    resp = await client.post(
        "/mcp/v1/",
        json={},
    )
    # empty dict is falsy in Python so the router returns -32600 "Invalid request"
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_mcp_invalid_json(client: AsyncClient):
    resp = await client.post(
        "/mcp/v1/",
        content=b"not json",
        headers={
            "Content-Type": "application/json",
            "Authorization": client.headers["authorization"],
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32700
