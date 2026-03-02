"""
API key validation against local cache — no Django dependency.

In monolith mode, reads from the shared PostgreSQL.
In gateway mode, reads from the local SQLite cache (synced from control plane).
"""

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import MCPApiKey, Project

logger = logging.getLogger(__name__)


async def validate_api_key(
    key: str, db: AsyncSession
) -> tuple[MCPApiKey, Project | None]:
    """
    Validate an MCP API key and resolve project context.

    Args:
        key: Raw API key string (e.g., "ak_live_xxx...")
        db: Database session

    Returns:
        Tuple of (MCPApiKey, Optional[Project])

    Raises:
        ValueError: If key is invalid, expired, or has no project binding
    """
    if not key:
        raise ValueError("Empty API key")

    prefix = key[:10] if len(key) >= 10 else key

    stmt = (
        select(MCPApiKey)
        .options(selectinload(MCPApiKey.project))
        .where(MCPApiKey.key_prefix == prefix)
        .where(MCPApiKey.is_active == True)  # noqa: E712
    )

    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise ValueError("Invalid API key")

    # Verify full key hash
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    if key_hash != api_key.key_hash:
        raise ValueError("Invalid API key")

    # Check expiration
    expires = api_key.expires_at
    if expires:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise ValueError("API key has expired")

    # Update last used
    try:
        await db.execute(
            text("UPDATE mcp_mcpapikey SET last_used_at = :ts WHERE id = :id"),
            {"ts": datetime.now(timezone.utc), "id": api_key.id},
        )
        await db.commit()
    except Exception:
        pass  # Non-fatal

    # Resolve project
    project = None
    if api_key.is_admin:
        project = None  # Admin tokens don't operate in project context
    elif api_key.project_id:
        project = api_key.project
    else:
        raise ValueError("Token has no project binding. Every regular token must be bound to a project.")

    return api_key, project
