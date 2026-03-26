"""Connection CRUD + test endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import encrypt_value
from ..database import get_db
from ..models.api_key import APIKey
from ..models.connection import Connection
from ..models.integration import Integration
from ..models.workspace import Workspace
from .deps import get_api_key

router = APIRouter(prefix="/api/v1/workspaces/{ws_slug}/connections", tags=["Connections"])


class ConnectionCreate(BaseModel):
    integration_slug: str
    credentials: dict = {}
    custom_settings: dict = {}
    base_url_override: str | None = None
    external_id: str | None = None


class ConnectionUpdate(BaseModel):
    credentials: dict | None = None
    custom_settings: dict | None = None
    base_url_override: str | None = None
    external_id: str | None = None
    is_enabled: bool | None = None


class ConnectionOut(BaseModel):
    id: str
    integration_id: str
    integration_slug: str | None = None
    base_url_override: str | None
    custom_settings: dict
    external_id: str | None
    is_enabled: bool
    is_verified: bool
    last_error: str | None

    model_config = {"from_attributes": True}


async def _get_workspace(ws_slug: str, api_key: APIKey, db: AsyncSession) -> Workspace:
    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == api_key.account_id,
            Workspace.slug == ws_slug,
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _encrypt_credentials(creds: dict) -> dict:
    """Encrypt sensitive credential values."""
    encrypted = {}
    for key, value in creds.items():
        if isinstance(value, str) and value:
            encrypted[key] = encrypt_value(value)
        else:
            encrypted[key] = value
    return encrypted


@router.get("/", response_model=list[ConnectionOut])
async def list_connections(
    ws_slug: str,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_workspace(ws_slug, api_key, db)
    result = await db.execute(
        select(Connection).where(Connection.workspace_id == ws.id)
    )
    connections = result.scalars().all()

    # Enrich with integration slug
    out = []
    for conn in connections:
        int_result = await db.execute(select(Integration.slug).where(Integration.id == conn.integration_id))
        int_slug = int_result.scalar_one_or_none()
        out.append(ConnectionOut(
            id=conn.id,
            integration_id=conn.integration_id,
            integration_slug=int_slug,
            base_url_override=conn.base_url_override,
            custom_settings=conn.custom_settings,
            external_id=conn.external_id,
            is_enabled=conn.is_enabled,
            is_verified=conn.is_verified,
            last_error=conn.last_error,
        ))
    return out


@router.post("/", response_model=ConnectionOut, status_code=201)
async def create_connection(
    ws_slug: str,
    body: ConnectionCreate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_workspace(ws_slug, api_key, db)

    # Find integration
    result = await db.execute(
        select(Integration).where(Integration.slug == body.integration_slug, Integration.is_active == True)  # noqa: E712
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Check for existing connection
    existing = await db.execute(
        select(Connection).where(
            Connection.workspace_id == ws.id,
            Connection.integration_id == integration.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Connection already exists for this integration")

    conn = Connection(
        workspace_id=ws.id,
        integration_id=integration.id,
        credentials=_encrypt_credentials(body.credentials),
        custom_settings=body.custom_settings,
        base_url_override=body.base_url_override,
        external_id=body.external_id,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    return ConnectionOut(
        id=conn.id,
        integration_id=conn.integration_id,
        integration_slug=body.integration_slug,
        base_url_override=conn.base_url_override,
        custom_settings=conn.custom_settings,
        external_id=conn.external_id,
        is_enabled=conn.is_enabled,
        is_verified=conn.is_verified,
        last_error=conn.last_error,
    )


@router.patch("/{integration_slug}", response_model=ConnectionOut)
async def update_connection(
    ws_slug: str,
    integration_slug: str,
    body: ConnectionUpdate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_workspace(ws_slug, api_key, db)

    result = await db.execute(
        select(Connection)
        .join(Integration)
        .where(
            Connection.workspace_id == ws.id,
            Integration.slug == integration_slug,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    if body.credentials is not None:
        conn.credentials = _encrypt_credentials(body.credentials)
    if body.custom_settings is not None:
        conn.custom_settings = body.custom_settings
    if body.base_url_override is not None:
        conn.base_url_override = body.base_url_override
    if body.external_id is not None:
        conn.external_id = body.external_id
    if body.is_enabled is not None:
        conn.is_enabled = body.is_enabled

    await db.commit()
    await db.refresh(conn)

    return ConnectionOut(
        id=conn.id,
        integration_id=conn.integration_id,
        integration_slug=integration_slug,
        base_url_override=conn.base_url_override,
        custom_settings=conn.custom_settings,
        external_id=conn.external_id,
        is_enabled=conn.is_enabled,
        is_verified=conn.is_verified,
        last_error=conn.last_error,
    )


@router.delete("/{integration_slug}", status_code=204)
async def delete_connection(
    ws_slug: str,
    integration_slug: str,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_workspace(ws_slug, api_key, db)
    result = await db.execute(
        select(Connection)
        .join(Integration)
        .where(
            Connection.workspace_id == ws.id,
            Integration.slug == integration_slug,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    await db.delete(conn)
    await db.commit()
