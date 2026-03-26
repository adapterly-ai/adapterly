"""Integration CRUD + OpenAPI import endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.api_key import APIKey
from ..models.integration import Integration, Tool
from .deps import get_api_key

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"])


class ToolOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    method: str
    path: str
    tool_type: str
    is_enabled: bool

    model_config = {"from_attributes": True}


class IntegrationOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    category: str
    base_url: str
    scope: str
    is_active: bool
    tools: list[ToolOut] = []

    model_config = {"from_attributes": True}


class IntegrationCreate(BaseModel):
    slug: str
    name: str
    description: str = ""
    category: str = "other"
    base_url: str = ""
    auth_config: dict = {}
    variables: dict = {}
    tools: list[dict] = []


@router.get("/", response_model=list[IntegrationOut])
async def list_integrations(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """List public integrations + own private integrations."""
    result = await db.execute(
        select(Integration)
        .options(selectinload(Integration.tools))
        .where(
            Integration.is_active == True,  # noqa: E712
            or_(
                Integration.scope == "public",
                Integration.account_id == api_key.account_id,
            ),
        )
    )
    return result.scalars().all()


@router.post("/", response_model=IntegrationOut, status_code=201)
async def create_integration(
    body: IntegrationCreate,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a private integration from JSON spec."""
    integration = Integration(
        slug=body.slug,
        name=body.name,
        description=body.description,
        category=body.category,
        base_url=body.base_url,
        auth_config=body.auth_config,
        variables=body.variables,
        scope="private",
        account_id=api_key.account_id,
    )
    db.add(integration)
    await db.flush()

    for tool_spec in body.tools:
        tool = Tool(
            integration_id=integration.id,
            slug=tool_spec["slug"],
            name=tool_spec.get("name", tool_spec["slug"]),
            description=tool_spec.get("description", ""),
            method=tool_spec.get("method", "GET"),
            path=tool_spec.get("path", ""),
            parameters_schema=tool_spec.get("parameters_schema", {}),
            pagination=tool_spec.get("pagination", {}),
            tool_type=tool_spec.get("tool_type", "read"),
            headers=tool_spec.get("headers", {}),
        )
        db.add(tool)

    await db.commit()
    await db.refresh(integration)
    # Reload with tools
    result = await db.execute(
        select(Integration).options(selectinload(Integration.tools)).where(Integration.id == integration.id)
    )
    return result.scalar_one()


@router.get("/{slug}", response_model=IntegrationOut)
async def get_integration(
    slug: str,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Integration)
        .options(selectinload(Integration.tools))
        .where(
            Integration.slug == slug,
            or_(
                Integration.scope == "public",
                Integration.account_id == api_key.account_id,
            ),
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.delete("/{slug}", status_code=204)
async def delete_integration(
    slug: str,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Delete a private integration (cannot delete public)."""
    result = await db.execute(
        select(Integration).where(
            Integration.slug == slug,
            Integration.scope == "private",
            Integration.account_id == api_key.account_id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Private integration not found")

    await db.delete(integration)
    await db.commit()
