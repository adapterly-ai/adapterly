"""
MCP Management Tools - Account and Workspace management via MCP.

These tools provide workspace and account management capabilities:
- workspace_create: Create or get workspace by external_id (idempotent)
- workspace_list: List account's workspaces
- workspace_get: Get workspace details
- account_get: Get account details
- admin_session_create: Create federated login session
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.accounts import Account
from ...models.clients import AdminSession, Workspace, WorkspaceMember
from ...models.mcp import Project

logger = logging.getLogger(__name__)


def get_management_tools() -> list[dict[str, Any]]:
    """Get all management tools."""
    return [
        # workspace_create
        {
            "name": "workspace_create",
            "description": "Create or get workspace by external_id (idempotent). Returns existing workspace if external_id exists.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "external_id": {
                        "type": "string",
                        "description": "External identifier for the workspace (unique per account)",
                    },
                    "name": {"type": "string", "description": "Display name for the workspace"},
                    "description": {"type": "string", "description": "Optional description of the workspace"},
                },
                "required": ["external_id", "name"],
            },
            "handler": workspace_create_handler,
        },
        # workspace_list
        {
            "name": "workspace_list",
            "description": "List all workspaces for the current account.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "include_inactive": {
                        "type": "boolean",
                        "description": "Include inactive workspaces (default: false)",
                    },
                },
            },
            "handler": workspace_list_handler,
        },
        # workspace_get
        {
            "name": "workspace_get",
            "description": "Get detailed workspace information by ID or external_id.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace UUID"},
                    "external_id": {"type": "string", "description": "External workspace identifier"},
                },
            },
            "handler": workspace_get_handler,
        },
        # account_get
        {
            "name": "account_get",
            "description": "Get account information for the current context.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": account_get_handler,
        },
        # admin_session_create
        {
            "name": "admin_session_create",
            "description": "Create a federated login session for Adapterly UI. Returns a one-time session token.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Optional workspace UUID to scope the session"},
                    "end_user_issuer": {
                        "type": "string",
                        "description": "Identity provider URL (e.g., https://accounts.google.com)",
                    },
                    "end_user_subject": {"type": "string", "description": "User identifier from identity provider"},
                    "role": {
                        "type": "string",
                        "enum": ["account_admin", "workspace_admin", "viewer"],
                        "description": "Role for the session",
                    },
                    "expires_in_seconds": {
                        "type": "integer",
                        "description": "Session validity in seconds (60-3600, default: 300)",
                    },
                },
                "required": ["end_user_issuer", "end_user_subject", "role"],
            },
            "handler": admin_session_create_handler,
        },
        # project_create
        {
            "name": "project_create",
            "description": "Create a new project with external system mappings. Projects scope API operations to specific external identifiers.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "URL-safe identifier for the project (unique per account)",
                    },
                    "name": {"type": "string", "description": "Display name for the project"},
                    "description": {"type": "string", "description": "Optional description of the project"},
                    "external_mappings": {
                        "type": "object",
                        "description": 'Maps system aliases to external IDs, e.g., {"jira": "PROJ-123", "github": "org/repo"}',
                    },
                },
                "required": ["slug", "name"],
            },
            "handler": project_create_handler,
        },
        # project_list
        {
            "name": "project_list",
            "description": "List all projects for the current account.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "include_inactive": {
                        "type": "boolean",
                        "description": "Include inactive projects (default: false)",
                    },
                },
            },
            "handler": project_list_handler,
        },
        # project_get
        {
            "name": "project_get",
            "description": "Get project details by slug or ID. If no arguments provided, returns the current project context.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Project slug"},
                    "project_id": {"type": "integer", "description": "Project ID"},
                },
            },
            "handler": project_get_handler,
        },
        # project_map
        {
            "name": "project_map",
            "description": "Add or update an external system mapping for a project.",
            "tool_type": "management",
            "input_schema": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Project slug"},
                    "system_alias": {
                        "type": "string",
                        "description": 'System alias (e.g., "jira", "github", "salesforce")',
                    },
                    "external_id": {"type": "string", "description": "External project identifier in the system"},
                    "config": {"type": "object", "description": "Optional additional configuration for this mapping"},
                },
                "required": ["slug", "system_alias", "external_id"],
            },
            "handler": project_map_handler,
        },
    ]


# Tool Handlers


async def workspace_create_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Create or get workspace by external_id (idempotent)."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")

    external_id = kwargs.get("external_id")
    name = kwargs.get("name")
    description = kwargs.get("description", "")

    if not external_id or not name:
        return {"error": "external_id and name are required"}

    try:
        # Check if workspace already exists
        stmt = select(Workspace).where(Workspace.account_id == account_id).where(Workspace.external_id == external_id)
        result = await db.execute(stmt)
        workspace = result.scalar_one_or_none()

        if workspace:
            # Update if needed
            updated = False
            if workspace.name != name:
                workspace.name = name
                updated = True
            if description and workspace.description != description:
                workspace.description = description
                updated = True
            if updated:
                workspace.updated_at = datetime.utcnow()
                await db.commit()

            return {
                "workspace_id": str(workspace.id),
                "external_id": workspace.external_id,
                "name": workspace.name,
                "description": workspace.description or "",
                "is_active": workspace.is_active,
                "created": False,
                "created_at": workspace.created_at.isoformat(),
            }

        # Create new workspace
        workspace = Workspace(
            id=str(uuid.uuid4()),
            account_id=account_id,
            external_id=external_id,
            name=name,
            description=description,
        )
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)

        return {
            "workspace_id": str(workspace.id),
            "external_id": workspace.external_id,
            "name": workspace.name,
            "description": workspace.description or "",
            "is_active": workspace.is_active,
            "created": True,
            "created_at": workspace.created_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
        await db.rollback()
        return {"error": str(e)}


async def workspace_list_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """List all workspaces for the account."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")
    include_inactive = kwargs.get("include_inactive", False)

    try:
        stmt = select(Workspace).where(Workspace.account_id == account_id)
        if not include_inactive:
            stmt = stmt.where(Workspace.is_active == True)  # noqa: E712
        stmt = stmt.order_by(Workspace.name)

        result = await db.execute(stmt)
        workspaces = result.scalars().all()

        workspace_list = []
        for ws in workspaces:
            workspace_list.append(
                {
                    "workspace_id": str(ws.id),
                    "external_id": ws.external_id,
                    "name": ws.name,
                    "description": ws.description or "",
                    "is_active": ws.is_active,
                    "created_at": ws.created_at.isoformat(),
                }
            )

        return {"workspaces": workspace_list, "count": len(workspace_list)}

    except Exception as e:
        logger.error(f"Failed to list workspaces: {e}")
        return {"error": str(e)}


async def workspace_get_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Get workspace details by ID or external_id."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")

    workspace_id = kwargs.get("workspace_id")
    external_id = kwargs.get("external_id")

    if not workspace_id and not external_id:
        return {"error": "Either workspace_id or external_id is required"}

    try:
        if workspace_id:
            stmt = select(Workspace).where(Workspace.id == workspace_id).where(Workspace.account_id == account_id)
        else:
            stmt = (
                select(Workspace).where(Workspace.external_id == external_id).where(Workspace.account_id == account_id)
            )

        result = await db.execute(stmt)
        workspace = result.scalar_one_or_none()

        if not workspace:
            return {"error": "Workspace not found"}

        # Get member count
        member_count_stmt = (
            select(func.count(WorkspaceMember.id))
            .where(WorkspaceMember.workspace_id == workspace.id)
            .where(WorkspaceMember.is_active == True)  # noqa: E712
        )
        member_count_result = await db.execute(member_count_stmt)
        member_count = member_count_result.scalar() or 0

        return {
            "workspace_id": str(workspace.id),
            "external_id": workspace.external_id,
            "name": workspace.name,
            "description": workspace.description or "",
            "is_active": workspace.is_active,
            "member_count": member_count,
            "inherit_account_systems": workspace.inherit_account_systems,
            "settings": workspace.settings,
            "created_at": workspace.created_at.isoformat(),
            "updated_at": workspace.updated_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get workspace: {e}")
        return {"error": str(e)}


async def account_get_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Get account information for the current context."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")

    try:
        stmt = select(Account).where(Account.id == account_id)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if not account:
            return {"error": "Account not found"}

        # Get workspace count
        workspace_count_stmt = (
            select(func.count(Workspace.id))
            .where(Workspace.account_id == account_id)
            .where(Workspace.is_active == True)  # noqa: E712
        )
        workspace_count_result = await db.execute(workspace_count_stmt)
        workspace_count = workspace_count_result.scalar() or 0

        return {
            "account_id": account.id,
            "name": account.name,
            "external_id": account.external_id,
            "workspace_count": workspace_count,
            "created_at": account.created_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get account: {e}")
        return {"error": str(e)}


async def admin_session_create_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Create a federated login session for Adapterly UI."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")

    workspace_id = kwargs.get("workspace_id")
    end_user_issuer = kwargs.get("end_user_issuer")
    end_user_subject = kwargs.get("end_user_subject")
    role = kwargs.get("role")
    expires_in_seconds = kwargs.get("expires_in_seconds", 300)

    if not all([end_user_issuer, end_user_subject, role]):
        return {"error": "end_user_issuer, end_user_subject, and role are required"}

    if role not in ("account_admin", "workspace_admin", "viewer"):
        return {"error": "Role must be one of: account_admin, workspace_admin, viewer"}

    # Validate expires_in_seconds
    if expires_in_seconds < 60:
        expires_in_seconds = 60
    elif expires_in_seconds > 3600:
        expires_in_seconds = 3600

    try:
        # Verify workspace if provided
        if workspace_id:
            stmt = select(Workspace).where(Workspace.id == workspace_id).where(Workspace.account_id == account_id)
            result = await db.execute(stmt)
            workspace = result.scalar_one_or_none()
            if not workspace:
                return {"error": "Workspace not found"}

        # Create session
        session = AdminSession(
            id=str(uuid.uuid4()),
            session_token=AdminSession.generate_token(),
            account_id=account_id,
            workspace_id=workspace_id,
            end_user_issuer=end_user_issuer,
            end_user_subject=end_user_subject,
            role=role,
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        return {
            "session_id": str(session.id),
            "session_token": session.session_token,
            "account_id": account_id,
            "workspace_id": workspace_id,
            "role": role,
            "end_user_issuer": end_user_issuer,
            "end_user_subject": end_user_subject,
            "expires_at": session.expires_at.isoformat(),
            "login_url": f"/auth/federated/{session.session_token}/",
        }

    except Exception as e:
        logger.error(f"Failed to create admin session: {e}")
        await db.rollback()
        return {"error": str(e)}


# Project Management Tools


async def project_create_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Create or update a project with external system mappings."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")

    slug = kwargs.get("slug")
    name = kwargs.get("name")
    description = kwargs.get("description", "")
    external_mappings = kwargs.get("external_mappings", {})

    if not slug or not name:
        return {"error": "slug and name are required"}

    try:
        # Check if project already exists
        stmt = select(Project).where(Project.account_id == account_id).where(Project.slug == slug)
        result = await db.execute(stmt)
        project = result.scalar_one_or_none()

        if project:
            # Update existing project
            updated = False
            if project.name != name:
                project.name = name
                updated = True
            if description and project.description != description:
                project.description = description
                updated = True
            if external_mappings:
                # Merge mappings
                current = project.external_mappings or {}
                current.update(external_mappings)
                project.external_mappings = current
                updated = True
            if updated:
                project.updated_at = datetime.utcnow()
                await db.commit()

            return {
                "project_id": project.id,
                "slug": project.slug,
                "name": project.name,
                "description": project.description or "",
                "external_mappings": project.external_mappings or {},
                "is_active": project.is_active,
                "created": False,
                "created_at": project.created_at.isoformat(),
            }

        # Create new project
        project = Project(
            account_id=account_id,
            slug=slug,
            name=name,
            description=description,
            external_mappings=external_mappings,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)

        return {
            "project_id": project.id,
            "slug": project.slug,
            "name": project.name,
            "description": project.description or "",
            "external_mappings": project.external_mappings or {},
            "is_active": project.is_active,
            "created": True,
            "created_at": project.created_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        await db.rollback()
        return {"error": str(e)}


async def project_list_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """List all projects for the account."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")
    include_inactive = kwargs.get("include_inactive", False)

    try:
        stmt = select(Project).where(Project.account_id == account_id)
        if not include_inactive:
            stmt = stmt.where(Project.is_active == True)  # noqa: E712
        stmt = stmt.order_by(Project.name)

        result = await db.execute(stmt)
        projects = result.scalars().all()

        project_list = []
        for proj in projects:
            project_list.append(
                {
                    "project_id": proj.id,
                    "slug": proj.slug,
                    "name": proj.name,
                    "description": proj.description or "",
                    "external_mappings": proj.external_mappings or {},
                    "is_active": proj.is_active,
                    "created_at": proj.created_at.isoformat(),
                }
            )

        return {"projects": project_list, "count": len(project_list)}

    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        return {"error": str(e)}


async def project_get_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Get project details by slug or ID, or return current project context."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")
    current_project = ctx.get("project")

    slug = kwargs.get("slug")
    project_id = kwargs.get("project_id")

    # If no arguments, return current project context
    if not slug and not project_id:
        if current_project:
            return {
                "project_id": current_project.id,
                "slug": current_project.slug,
                "name": current_project.name,
                "description": current_project.description or "",
                "external_mappings": current_project.external_mappings or {},
                "is_active": current_project.is_active,
                "is_current_context": True,
                "created_at": current_project.created_at.isoformat(),
            }
        return {"project": None, "message": "No project context set for this session"}

    try:
        if project_id:
            stmt = select(Project).where(Project.id == project_id).where(Project.account_id == account_id)
        else:
            stmt = select(Project).where(Project.slug == slug).where(Project.account_id == account_id)

        result = await db.execute(stmt)
        project = result.scalar_one_or_none()

        if not project:
            return {"error": "Project not found"}

        return {
            "project_id": project.id,
            "slug": project.slug,
            "name": project.name,
            "description": project.description or "",
            "external_mappings": project.external_mappings or {},
            "is_active": project.is_active,
            "is_current_context": current_project and current_project.id == project.id,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        }

    except Exception as e:
        logger.error(f"Failed to get project: {e}")
        return {"error": str(e)}


async def project_map_handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Add or update an external system mapping for a project."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")

    slug = kwargs.get("slug")
    system_alias = kwargs.get("system_alias")
    external_id = kwargs.get("external_id")
    config = kwargs.get("config", {})

    if not all([slug, system_alias, external_id]):
        return {"error": "slug, system_alias, and external_id are required"}

    try:
        # Get project
        stmt = select(Project).where(Project.slug == slug).where(Project.account_id == account_id)
        result = await db.execute(stmt)
        project = result.scalar_one_or_none()

        if not project:
            return {"error": f"Project not found: {slug}"}

        # Update external_mappings JSON
        mappings = project.external_mappings or {}
        mappings[system_alias] = external_id
        project.external_mappings = mappings
        project.updated_at = datetime.utcnow()

        await db.commit()

        return {
            "project_id": project.id,
            "slug": project.slug,
            "system_alias": system_alias,
            "external_id": external_id,
            "config": config,
            "message": f"Mapped {system_alias} -> {external_id} for project {slug}",
        }

    except Exception as e:
        logger.error(f"Failed to map project: {e}")
        await db.rollback()
        return {"error": str(e)}
