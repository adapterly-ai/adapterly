"""
Audit reporter — pushes buffered audit log entries to the control plane.

Runs every AUDIT_PUSH_INTERVAL seconds (default 30s) or when batch size is reached.
"""

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_core.models import MCPAuditLog

from ..config import get_settings
from ..database import get_db_context

logger = logging.getLogger(__name__)


async def push_audit_once():
    """Push unsynced audit entries to the control plane."""
    settings = get_settings()

    if not settings.gateway_secret:
        return

    async with get_db_context() as db:
        # Get unsynced entries
        stmt = (
            select(MCPAuditLog)
            .where(MCPAuditLog.synced == False)  # noqa: E712
            .order_by(MCPAuditLog.timestamp)
            .limit(settings.audit_push_batch_size)
        )
        result = await db.execute(stmt)
        entries = result.scalars().all()

        if not entries:
            return

        # Build payload
        payload = {
            "entries": [
                {
                    "tool_name": e.tool_name,
                    "tool_type": e.tool_type,
                    "duration_ms": e.duration_ms,
                    "success": e.success,
                    "error_message": e.error_message or "",
                    "error_category": "",
                    "session_id": e.session_id or "",
                    "mode": e.mode or "safe",
                    "timestamp": e.timestamp.isoformat() if e.timestamp else datetime.utcnow().isoformat(),
                }
                for e in entries
            ]
        }

        url = f"{settings.control_plane_url.rstrip('/')}/gateway-sync/v1/audit"
        headers = {"Authorization": f"Bearer {settings.gateway_secret}"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30)
                response.raise_for_status()

            # Mark as synced
            entry_ids = [e.id for e in entries]
            await db.execute(
                update(MCPAuditLog)
                .where(MCPAuditLog.id.in_(entry_ids))
                .values(synced=True)
            )
            await db.commit()

            logger.info(f"Pushed {len(entries)} audit entries to control plane")

        except httpx.HTTPStatusError as e:
            logger.error(f"Audit push failed: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"Audit push failed: {e}")


async def audit_push_loop():
    """Background loop that pushes audit entries periodically."""
    settings = get_settings()
    interval = settings.audit_push_interval

    while True:
        await asyncio.sleep(interval)
        try:
            await push_audit_once()
        except Exception as e:
            logger.error(f"Audit push loop error: {e}")
