"""
Key sync — pulls API keys, projects, and integrations from the control plane.

Runs every KEY_SYNC_INTERVAL seconds (default 1 min).
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_core.models import MCPApiKey, Project, ProjectIntegration

from ..config import get_settings
from ..database import get_db_context

logger = logging.getLogger(__name__)

_last_sync: datetime | None = None


async def sync_keys_once():
    """Pull keys, projects, and integrations from control plane."""
    global _last_sync
    settings = get_settings()

    if not settings.gateway_secret:
        logger.warning("No gateway secret configured, skipping key sync")
        return

    url = f"{settings.control_plane_url.rstrip('/')}/gateway-sync/v1/keys"
    params = {}
    if _last_sync:
        params["since"] = _last_sync.isoformat()

    headers = {"Authorization": f"Bearer {settings.gateway_secret}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

        async with get_db_context() as db:
            # Upsert projects
            for proj_data in data.get("projects", []):
                await _upsert_project(db, proj_data)

            # Upsert API keys
            for key_data in data.get("keys", []):
                await _upsert_api_key(db, key_data)

            # Upsert integrations
            for integ_data in data.get("integrations", []):
                await _upsert_integration(db, integ_data)

            await db.commit()

        _last_sync = datetime.now(timezone.utc)
        logger.info(
            f"Key sync complete: {len(data.get('keys', []))} keys, "
            f"{len(data.get('projects', []))} projects, "
            f"{len(data.get('integrations', []))} integrations"
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"Key sync failed: HTTP {e.response.status_code}")
    except Exception as e:
        logger.error(f"Key sync failed: {e}")


async def _upsert_project(db: AsyncSession, data: dict):
    existing = await db.execute(select(Project).where(Project.id == data["id"]))
    project = existing.scalar_one_or_none()

    if project:
        for key in ["name", "slug", "description", "external_mappings", "is_active", "account_id"]:
            if key in data:
                setattr(project, key, data[key])
        project.updated_at = datetime.utcnow()
    else:
        project = Project(
            id=data["id"],
            account_id=data["account_id"],
            name=data["name"],
            slug=data["slug"],
            description=data.get("description", ""),
            external_mappings=data.get("external_mappings", {}),
            is_active=data.get("is_active", True),
        )
        db.add(project)


async def _upsert_api_key(db: AsyncSession, data: dict):
    existing = await db.execute(select(MCPApiKey).where(MCPApiKey.id == data["id"]))
    key = existing.scalar_one_or_none()

    if key:
        for field in ["name", "key_prefix", "key_hash", "project_id", "is_admin",
                       "mode", "allowed_tools", "blocked_tools", "is_active", "expires_at"]:
            if field in data:
                setattr(key, field, data[field])
    else:
        key = MCPApiKey(
            id=data["id"],
            account_id=data["account_id"],
            name=data["name"],
            key_prefix=data["key_prefix"],
            key_hash=data["key_hash"],
            project_id=data.get("project_id"),
            is_admin=data.get("is_admin", False),
            mode=data.get("mode", "safe"),
            allowed_tools=data.get("allowed_tools", []),
            blocked_tools=data.get("blocked_tools", []),
            is_active=data.get("is_active", True),
            expires_at=data.get("expires_at"),
        )
        db.add(key)


async def _upsert_integration(db: AsyncSession, data: dict):
    existing = await db.execute(select(ProjectIntegration).where(ProjectIntegration.id == data["id"]))
    integ = existing.scalar_one_or_none()

    if integ:
        for field in ["project_id", "system_id", "credential_source", "external_id",
                       "is_enabled", "custom_config"]:
            if field in data:
                setattr(integ, field, data[field])
        integ.updated_at = datetime.utcnow()
    else:
        integ = ProjectIntegration(
            id=data["id"],
            project_id=data["project_id"],
            system_id=data["system_id"],
            credential_source=data.get("credential_source", "account"),
            external_id=data.get("external_id", ""),
            is_enabled=data.get("is_enabled", True),
            custom_config=data.get("custom_config", {}),
        )
        db.add(integ)


async def key_sync_loop():
    """Background loop that syncs keys periodically."""
    settings = get_settings()
    interval = settings.key_sync_interval

    await sync_keys_once()

    while True:
        await asyncio.sleep(interval)
        try:
            await sync_keys_once()
        except Exception as e:
            logger.error(f"Key sync loop error: {e}")
