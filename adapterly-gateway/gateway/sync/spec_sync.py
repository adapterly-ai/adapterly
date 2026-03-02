"""
Spec sync — pulls adapter specs from the control plane.

Runs every SPEC_SYNC_INTERVAL seconds (default 5 min).
Stores specs in local SQLite (read-only cache).
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_core.models import Action, Interface, Resource, System

from ..config import get_settings
from ..database import get_db_context

logger = logging.getLogger(__name__)

_last_sync: datetime | None = None


async def sync_specs_once():
    """Pull specs from control plane and upsert into local DB."""
    global _last_sync
    settings = get_settings()

    if not settings.gateway_secret:
        logger.warning("No gateway secret configured, skipping spec sync")
        return

    url = f"{settings.control_plane_url.rstrip('/')}/gateway-sync/v1/specs"
    params = {}
    if _last_sync:
        params["since"] = _last_sync.isoformat()

    headers = {"Authorization": f"Bearer {settings.gateway_secret}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()

        async with get_db_context() as db:
            # Process deleted systems
            deleted_ids = data.get("deleted_ids", [])
            if deleted_ids:
                await db.execute(delete(System).where(System.id.in_(deleted_ids)))
                logger.info(f"Deleted {len(deleted_ids)} systems")

            # Upsert systems
            for sys_data in data.get("systems", []):
                await _upsert_system(db, sys_data)

            await db.commit()

        _last_sync = datetime.now(timezone.utc)
        logger.info(
            f"Spec sync complete: {len(data.get('systems', []))} systems, "
            f"{len(deleted_ids)} deleted"
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"Spec sync failed: HTTP {e.response.status_code}")
    except Exception as e:
        logger.error(f"Spec sync failed: {e}")


async def _upsert_system(db: AsyncSession, sys_data: dict):
    """Upsert a system and its interfaces/resources/actions."""
    # Upsert system
    existing = await db.execute(select(System).where(System.id == sys_data["id"]))
    system = existing.scalar_one_or_none()

    if system:
        for key in ["name", "alias", "display_name", "description", "variables", "meta",
                     "schema_digest", "system_type", "icon", "website_url", "docs_url", "is_active"]:
            setattr(system, key, sys_data.get(key, getattr(system, key)))
        system.updated_at = datetime.utcnow()
    else:
        system = System(
            id=sys_data["id"],
            name=sys_data["name"],
            alias=sys_data["alias"],
            display_name=sys_data["display_name"],
            description=sys_data.get("description", ""),
            variables=sys_data.get("variables", {}),
            meta=sys_data.get("meta", {}),
            schema_digest=sys_data.get("schema_digest", ""),
            system_type=sys_data["system_type"],
            icon=sys_data.get("icon", ""),
            website_url=sys_data.get("website_url", ""),
            docs_url=sys_data.get("docs_url", ""),
            is_active=sys_data.get("is_active", True),
        )
        db.add(system)

    # Upsert interfaces
    for iface_data in sys_data.get("interfaces", []):
        existing = await db.execute(select(Interface).where(Interface.id == iface_data["id"]))
        iface = existing.scalar_one_or_none()
        if iface:
            for key in ["alias", "name", "type", "base_url", "auth", "requires_browser",
                         "browser", "rate_limits", "graphql_schema"]:
                setattr(iface, key, iface_data.get(key, getattr(iface, key)))
        else:
            iface = Interface(
                id=iface_data["id"],
                system_id=sys_data["id"],
                alias=iface_data.get("alias", ""),
                name=iface_data["name"],
                type=iface_data["type"],
                base_url=iface_data.get("base_url", ""),
                auth=iface_data.get("auth", {}),
                requires_browser=iface_data.get("requires_browser", False),
                browser=iface_data.get("browser", {}),
                rate_limits=iface_data.get("rate_limits", {}),
                graphql_schema=iface_data.get("graphql_schema", {}),
            )
            db.add(iface)

    # Upsert resources
    for res_data in sys_data.get("resources", []):
        existing = await db.execute(select(Resource).where(Resource.id == res_data["id"]))
        res = existing.scalar_one_or_none()
        if res:
            for key in ["alias", "name", "description"]:
                setattr(res, key, res_data.get(key, getattr(res, key)))
        else:
            res = Resource(
                id=res_data["id"],
                interface_id=res_data["interface_id"],
                alias=res_data.get("alias", ""),
                name=res_data["name"],
                description=res_data.get("description", ""),
            )
            db.add(res)

    # Upsert actions
    for act_data in sys_data.get("actions", []):
        existing = await db.execute(select(Action).where(Action.id == act_data["id"]))
        act = existing.scalar_one_or_none()
        if act:
            for key in ["alias", "name", "description", "method", "path", "headers",
                         "parameters_schema", "output_schema", "pagination", "errors",
                         "examples", "is_mcp_enabled"]:
                setattr(act, key, act_data.get(key, getattr(act, key)))
            act.updated_at = datetime.utcnow()
        else:
            act = Action(
                id=act_data["id"],
                resource_id=act_data["resource_id"],
                alias=act_data.get("alias", ""),
                name=act_data["name"],
                description=act_data.get("description", ""),
                method=act_data["method"],
                path=act_data["path"],
                headers=act_data.get("headers", {}),
                parameters_schema=act_data.get("parameters_schema", {}),
                output_schema=act_data.get("output_schema", {}),
                pagination=act_data.get("pagination", {}),
                errors=act_data.get("errors", {}),
                examples=act_data.get("examples", []),
                is_mcp_enabled=act_data.get("is_mcp_enabled", True),
            )
            db.add(act)


async def spec_sync_loop():
    """Background loop that syncs specs periodically."""
    settings = get_settings()
    interval = settings.spec_sync_interval

    # Initial sync
    await sync_specs_once()

    while True:
        await asyncio.sleep(interval)
        try:
            await sync_specs_once()
        except Exception as e:
            logger.error(f"Spec sync loop error: {e}")
