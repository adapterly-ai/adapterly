"""Tests for /api/v1/integrations REST endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from adapterly.models import Integration


@pytest.mark.asyncio
async def test_list_integrations_empty(client: AsyncClient):
    """When no integrations exist, the list should be empty."""
    resp = await client.get("/api/v1/integrations/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_create_integration(client: AsyncClient):
    resp = await client.post(
        "/api/v1/integrations/",
        json={
            "slug": "github",
            "name": "GitHub",
            "description": "GitHub REST API",
            "category": "devtools",
            "base_url": "https://api.github.com",
            "auth_config": {"type": "bearer"},
            "tools": [
                {
                    "slug": "repos_list",
                    "name": "List Repos",
                    "description": "List user repos",
                    "method": "GET",
                    "path": "/user/repos",
                    "tool_type": "read",
                },
                {
                    "slug": "repo_create",
                    "name": "Create Repo",
                    "method": "POST",
                    "path": "/user/repos",
                    "tool_type": "write",
                },
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "github"
    assert data["name"] == "GitHub"
    assert data["scope"] == "private"
    assert data["is_active"] is True
    assert len(data["tools"]) == 2


@pytest.mark.asyncio
async def test_list_integrations_after_create(client: AsyncClient):
    # Create one first
    await client.post(
        "/api/v1/integrations/",
        json={
            "slug": "slack",
            "name": "Slack",
            "base_url": "https://slack.com/api",
            "tools": [],
        },
    )
    resp = await client.get("/api/v1/integrations/")
    assert resp.status_code == 200
    data = resp.json()
    slugs = [i["slug"] for i in data]
    assert "slack" in slugs


@pytest.mark.asyncio
async def test_get_integration_by_slug(client: AsyncClient, test_integration: Integration):
    resp = await client.get(f"/api/v1/integrations/{test_integration.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "test-api"
    assert data["name"] == "Test API"
    assert len(data["tools"]) == 2


@pytest.mark.asyncio
async def test_get_integration_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/integrations/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_integration(client: AsyncClient, test_integration: Integration):
    resp = await client.delete(f"/api/v1/integrations/{test_integration.slug}")
    assert resp.status_code == 204

    # Verify it's gone
    resp2 = await client.get(f"/api/v1/integrations/{test_integration.slug}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_delete_integration_not_found(client: AsyncClient):
    resp = await client.delete("/api/v1/integrations/ghost")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_integration_with_empty_tools(client: AsyncClient):
    resp = await client.post(
        "/api/v1/integrations/",
        json={
            "slug": "minimal",
            "name": "Minimal Integration",
            "tools": [],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tools"] == []
    assert data["category"] == "other"
    assert data["description"] == ""


@pytest.mark.asyncio
async def test_create_integration_defaults(client: AsyncClient):
    """Fields not supplied should use sensible defaults."""
    resp = await client.post(
        "/api/v1/integrations/",
        json={"slug": "defaults-test", "name": "Defaults"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["base_url"] == ""
    assert data["category"] == "other"
    assert data["description"] == ""
    assert data["scope"] == "private"
