"""Tests for GET /health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    """GET /health should return 200 with status, mode, and version."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"
    assert "mode" in data


@pytest.mark.asyncio
async def test_health_contains_mode(client: AsyncClient):
    """Health response should contain the deployment mode."""
    resp = await client.get("/health")
    data = resp.json()
    assert data["mode"] in ("standalone", "cloud")


@pytest.mark.asyncio
async def test_health_no_auth_required(client: AsyncClient):
    """Health endpoint should be accessible without auth."""
    # Make a request without the auth header
    from httpx import ASGITransport, AsyncClient as AC

    transport = client._transport
    async with AC(transport=transport, base_url="http://test") as no_auth_client:
        resp = await no_auth_client.get("/health")
        assert resp.status_code == 200
