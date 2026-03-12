"""
Health reporter — pushes heartbeat to the control plane.

Runs every HEALTH_PUSH_INTERVAL seconds (default 60s).
"""

import asyncio
import logging

import httpx
from sqlalchemy import func, select

from gateway_core.models import AccountSystem

from ..config import get_settings
from ..database import get_db_context

logger = logging.getLogger(__name__)


async def push_health_once():
    """Push health status to control plane."""
    settings = get_settings()

    if not settings.gateway_secret:
        return

    # Build credential status
    credential_status = {}
    try:
        async with get_db_context() as db:
            stmt = (
                select(AccountSystem.system_id, func.count())
                .where(AccountSystem.is_enabled == True)  # noqa: E712
                .group_by(AccountSystem.system_id)
            )
            result = await db.execute(stmt)
            for system_id, count in result.fetchall():
                credential_status[str(system_id)] = count > 0
    except Exception:
        pass

    payload = {
        "status": "healthy",
        "active_sessions": 0,  # TODO: track from MCP session manager
        "version": "0.1.0",
        "hostname": "",
        "credential_status": credential_status,
    }

    url = f"{settings.control_plane_url.rstrip('/')}/gateway-sync/v1/health"
    headers = {"Authorization": f"Bearer {settings.gateway_secret}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()

        logger.debug("Health push OK")

    except httpx.HTTPStatusError as e:
        logger.warning(f"Health push failed: HTTP {e.response.status_code}")
    except Exception as e:
        logger.warning(f"Health push failed: {e}")


async def health_push_loop():
    """Background loop that pushes health periodically."""
    settings = get_settings()
    interval = settings.health_push_interval

    while True:
        await asyncio.sleep(interval)
        try:
            await push_health_once()
        except Exception as e:
            logger.error(f"Health push loop error: {e}")
