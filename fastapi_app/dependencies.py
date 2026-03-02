"""
FastAPI dependencies for authentication, rate limiting, etc.
"""

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .database import get_db
from .models import MCPApiKey, Project  # imports trigger configure_mappers()


class APIKeyAuth:
    """API key authentication dependency with project resolution."""

    async def __call__(
        self, authorization: str = Header(None), db: AsyncSession = Depends(get_db)
    ) -> tuple[MCPApiKey, Project | None]:
        """
        Validate API key from Authorization header and resolve project context.

        Expected format: Bearer ak_live_xxx

        Project resolution:
        - Admin tokens: no project (management only)
        - Regular tokens: must have a bound project (403 otherwise)

        Returns:
            Tuple of (MCPApiKey, Optional[Project])
        """
        api_key = await self._validate_key(authorization, db)
        project = await self._resolve_project(api_key, db)

        return api_key, project

    async def _validate_key(self, authorization: str, db: AsyncSession) -> MCPApiKey:
        """Validate API key from Authorization header."""
        if not authorization:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header format")

        key = authorization[7:]  # Remove "Bearer " prefix

        if not key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty API key")

        # Extract prefix for lookup
        prefix = key[:10] if len(key) >= 10 else key

        # Find API key by prefix with project eager loading
        stmt = (
            select(MCPApiKey)
            .options(
                selectinload(MCPApiKey.account),
                selectinload(MCPApiKey.project),
                selectinload(MCPApiKey.profile),
            )
            .where(MCPApiKey.key_prefix == prefix)
            .where(MCPApiKey.is_active == True)  # noqa: E712
        )

        result = await db.execute(stmt)
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        # Verify full key hash
        if not api_key.check_key(key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        # Check expiration
        expires = api_key.expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires and expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key has expired")

        # Update last used timestamp using raw SQL to avoid FK constraint issues
        await db.execute(
            text("UPDATE mcp_mcpapikey SET last_used_at = :ts WHERE id = :id"),
            {"ts": datetime.now(timezone.utc), "id": api_key.id},
        )
        await db.commit()

        return api_key

    async def _resolve_project(self, api_key: MCPApiKey, db: AsyncSession) -> Project | None:
        """
        Resolve project context from API key.

        Rules:
        - Admin token → None (no project, management only)
        - Regular token with project → return bound project
        - Regular token without project → 403 (every regular token needs a project)
        """
        if api_key.is_admin:
            return None  # admin tokens don't operate in project context

        if not api_key.project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token has no project binding. Every regular token must be bound to a project.",
            )

        return api_key.project


class APIKeyOnlyAuth:
    """API key authentication dependency that only returns the API key (no project resolution)."""

    async def __call__(self, authorization: str = Header(None), db: AsyncSession = Depends(get_db)) -> MCPApiKey:
        """
        Validate API key from Authorization header.

        Expected format: Bearer ak_live_xxx
        """
        auth = APIKeyAuth()
        api_key, _ = await auth(authorization, db)
        return api_key


# Dependency instances
get_api_key_with_project = APIKeyAuth()
get_api_key = APIKeyOnlyAuth()


async def get_api_key_string(
    authorization: str = Header(None),
) -> str:
    """Extract raw API key string from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        return ""
    return authorization[7:]
