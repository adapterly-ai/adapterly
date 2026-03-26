"""Workspace CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.api_key import APIKey
from ..models.workspace import Workspace
from .deps import get_api_key

router = APIRouter(prefix="/api/v1/workspaces", tags=["Workspaces"])


class WorkspaceCreate(BaseModel):
    name: str
    slug: str
    description: str = ""


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[WorkspaceOut])
async def list_workspaces(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == api_key.account_id,
            Workspace.is_active == True,  # noqa: E712
        )
    )
    return result.scalars().all()


@router.post("/", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    # Check slug uniqueness within account
    existing = await db.execute(
        select(Workspace).where(
            Workspace.account_id == api_key.account_id,
            Workspace.slug == body.slug,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Workspace slug already exists")

    ws = Workspace(
        account_id=api_key.account_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


@router.get("/{slug}", response_model=WorkspaceOut)
async def get_workspace(
    slug: str,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == api_key.account_id,
            Workspace.slug == slug,
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.patch("/{slug}", response_model=WorkspaceOut)
async def update_workspace(
    slug: str,
    body: WorkspaceUpdate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == api_key.account_id,
            Workspace.slug == slug,
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if body.name is not None:
        ws.name = body.name
    if body.description is not None:
        ws.description = body.description

    await db.commit()
    await db.refresh(ws)
    return ws
