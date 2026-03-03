"""Tests for MCP router HTTP endpoints."""

import pytest
import pytest_asyncio

from .conftest import RAW_API_KEY, create_test_data


@pytest.mark.asyncio
class TestMCPRouter:
    """HTTP-level integration tests using httpx + ASGITransport."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_data(self, db):
        """Insert test data for every test."""
        self.data = await create_test_data(db)

    def _headers(self, key=None, session_id=None):
        h = {
            "Authorization": f"Bearer {key or RAW_API_KEY}",
            "Content-Type": "application/json",
        }
        if session_id:
            h["Mcp-Session-Id"] = session_id
        return h

    async def _initialize(self, client):
        """Send initialize and return session_id."""
        response = await client.post(
            "/mcp/v1/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers=self._headers(),
        )
        return response.headers.get("mcp-session-id"), response

    async def test_post_initialize(self, client):
        session_id, response = await self._initialize(client)
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["protocolVersion"] is not None
        assert data["result"]["serverInfo"]["name"] == "adapterly"
        assert session_id is not None

    async def test_post_tools_list(self, client):
        session_id, _ = await self._initialize(client)
        response = await client.post(
            "/mcp/v1/",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=self._headers(session_id=session_id),
        )
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data["result"]
        assert isinstance(data["result"]["tools"], list)

    async def test_post_ping(self, client):
        session_id, _ = await self._initialize(client)
        response = await client.post(
            "/mcp/v1/",
            json={"jsonrpc": "2.0", "id": 3, "method": "ping"},
            headers=self._headers(session_id=session_id),
        )
        assert response.status_code == 200
        assert response.json()["result"] == {}

    async def test_post_batch(self, client):
        session_id, _ = await self._initialize(client)
        response = await client.post(
            "/mcp/v1/",
            json=[
                {"jsonrpc": "2.0", "id": 10, "method": "ping"},
                {"jsonrpc": "2.0", "id": 11, "method": "ping"},
            ],
            headers=self._headers(session_id=session_id),
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    async def test_post_notification_202(self, client):
        session_id, _ = await self._initialize(client)
        response = await client.post(
            "/mcp/v1/",
            json={"jsonrpc": "2.0", "method": "initialized"},
            headers=self._headers(session_id=session_id),
        )
        assert response.status_code == 202

    async def test_post_invalid_json(self, client):
        response = await client.post(
            "/mcp/v1/",
            content=b"{invalid json",
            headers=self._headers(),
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == -32700

    async def test_post_empty_body(self, client):
        response = await client.post(
            "/mcp/v1/",
            json=None,
            headers=self._headers(),
        )
        # Empty body or null → parse error or invalid request
        assert response.status_code in (400, 422)

    async def test_post_no_auth_401(self, client):
        response = await client.post(
            "/mcp/v1/",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert response.status_code == 401

    async def test_post_invalid_key_401(self, client):
        response = await client.post(
            "/mcp/v1/",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers=self._headers(key="ak_invalid_completely_wrong"),
        )
        assert response.status_code == 401

    async def test_delete_session_204(self, client):
        session_id, _ = await self._initialize(client)
        response = await client.delete(
            "/mcp/v1/",
            headers=self._headers(session_id=session_id),
        )
        assert response.status_code == 204

    async def test_delete_no_session_404(self, client):
        response = await client.delete(
            "/mcp/v1/",
            headers=self._headers(),
        )
        assert response.status_code == 404

    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
