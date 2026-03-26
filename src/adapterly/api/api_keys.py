"""API Key CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.api_key import APIKey, generate_api_key
from .deps import get_api_key

router = APIRouter(prefix="/api/v1/api-keys", tags=["API Keys"])


class APIKeyCreate(BaseModel):
    name: str = "Default"
    workspace_id: str | None = None
    mode: str = "safe"
    is_admin: bool = False
    allowed_tools: list[str] = []
    blocked_tools: list[str] = []


class APIKeyUpdate(BaseModel):
    name: str | None = None
    mode: str | None = None
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    is_active: bool | None = None


class APIKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    workspace_id: str | None
    mode: str
    is_admin: bool
    allowed_tools: list
    blocked_tools: list
    is_active: bool

    model_config = {"from_attributes": True}


class APIKeyCreated(APIKeyOut):
    raw_key: str  # Only shown once at creation


@router.get("/", response_model=list[APIKeyOut])
async def list_api_keys(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(APIKey.account_id == api_key.account_id)
    )
    return result.scalars().all()


@router.post("/", response_model=APIKeyCreated, status_code=201)
async def create_api_key(
    body: APIKeyCreate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    raw_key, prefix, key_hash = generate_api_key()

    new_key = APIKey(
        account_id=api_key.account_id,
        workspace_id=body.workspace_id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        mode=body.mode,
        is_admin=body.is_admin,
        allowed_tools=body.allowed_tools,
        blocked_tools=body.blocked_tools,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    return APIKeyCreated(
        id=new_key.id,
        name=new_key.name,
        key_prefix=new_key.key_prefix,
        workspace_id=new_key.workspace_id,
        mode=new_key.mode,
        is_admin=new_key.is_admin,
        allowed_tools=new_key.allowed_tools,
        blocked_tools=new_key.blocked_tools,
        is_active=new_key.is_active,
        raw_key=raw_key,
    )


@router.patch("/{key_id}", response_model=APIKeyOut)
async def update_api_key(
    key_id: str,
    body: APIKeyUpdate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.account_id == api_key.account_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="API key not found")

    if body.name is not None:
        target.name = body.name
    if body.mode is not None:
        target.mode = body.mode
    if body.allowed_tools is not None:
        target.allowed_tools = body.allowed_tools
    if body.blocked_tools is not None:
        target.blocked_tools = body.blocked_tools
    if body.is_active is not None:
        target.is_active = body.is_active

    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(
    key_id: str,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.account_id == api_key.account_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(target)
    await db.commit()
