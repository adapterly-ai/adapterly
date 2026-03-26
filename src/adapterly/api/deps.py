"""Shared FastAPI dependencies: DB session, auth, current account."""

from __future__ import annotations

import hashlib
import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.api_key import APIKey
from ..models.workspace import Workspace

logger = logging.getLogger(__name__)


async def get_api_key(
    authorization: str = Header(..., description="Bearer <api_key>"),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    """Resolve API key from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")

    raw_key = authorization[7:]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return api_key


async def get_api_key_with_workspace(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> tuple[APIKey, Workspace | None]:
    """Return API key and its workspace (if scoped)."""
    workspace = None
    if api_key.workspace_id:
        result = await db.execute(
            select(Workspace).where(Workspace.id == api_key.workspace_id)
        )
        workspace = result.scalar_one_or_none()
    return api_key, workspace


# Convenience type aliases
CurrentAPIKey = Annotated[APIKey, Depends(get_api_key)]
DB = Annotated[AsyncSession, Depends(get_db)]
