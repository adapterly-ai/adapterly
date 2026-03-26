"""Tests for /api/v1/workspaces REST endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_workspaces(client: AsyncClient, test_workspace):
    resp = await client.get("/api/v1/workspaces/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    slugs = [ws["slug"] for ws in data]
    assert "default" in slugs


@pytest.mark.asyncio
async def test_create_workspace(client: AsyncClient):
    resp = await client.post(
        "/api/v1/workspaces/",
        json={"name": "Production", "slug": "production", "description": "Prod env"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Production"
    assert data["slug"] == "production"
    assert data["description"] == "Prod env"
    assert data["is_active"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_create_workspace_duplicate_slug(client: AsyncClient, test_workspace):
    resp = await client.post(
        "/api/v1/workspaces/",
        json={"name": "Another", "slug": "default"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_workspace_by_slug(client: AsyncClient, test_workspace):
    resp = await client.get("/api/v1/workspaces/default")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "default"
    assert data["name"] == "Default Workspace"


@pytest.mark.asyncio
async def test_get_workspace_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/workspaces/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_workspace(client: AsyncClient, test_workspace):
    resp = await client.patch(
        "/api/v1/workspaces/default",
        json={"name": "Updated Name", "description": "Updated description"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"
    # slug should not change
    assert data["slug"] == "default"


@pytest.mark.asyncio
async def test_update_workspace_partial(client: AsyncClient, test_workspace):
    """PATCH with only name should not touch description."""
    resp = await client.patch(
        "/api/v1/workspaces/default",
        json={"name": "Only Name Changed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Only Name Changed"
    assert data["description"] == "Workspace for testing"  # unchanged


@pytest.mark.asyncio
async def test_update_workspace_not_found(client: AsyncClient):
    resp = await client.patch(
        "/api/v1/workspaces/ghost",
        json={"name": "Nope"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_workspaces_requires_auth(client: AsyncClient):
    """Request without Bearer token should 401 or 422."""
    from httpx import ASGITransport, AsyncClient as AC

    transport = client._transport
    async with AC(transport=transport, base_url="http://test") as no_auth:
        resp = await no_auth.get("/api/v1/workspaces/")
        assert resp.status_code in (401, 422)
