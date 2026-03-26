"""MCP meta-tools for managing integrations and connections via Claude Code."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.api_key import APIKey
from ..models.connection import Connection
from ..models.integration import Integration, Tool
from ..models.workspace import Workspace
from ..crypto import encrypt_value
from .session import MCPSession

logger = logging.getLogger(__name__)


META_TOOLS = [
    {
        "name": "integration_list",
        "description": "List all available integrations (public + private)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "integration_inspect",
        "description": "Show all tools for an integration",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Integration slug"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "integration_create",
        "description": "Create a new private integration from a JSON spec",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": "Integration spec with slug, name, base_url, auth_config, tools[]",
                },
            },
            "required": ["spec"],
        },
    },
    {
        "name": "integration_create_from_openapi",
        "description": "Create a new integration from an OpenAPI spec URL",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to the OpenAPI JSON spec"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "integration_delete",
        "description": "Delete a private integration",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Integration slug"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "connection_create",
        "description": "Connect an integration to a workspace with credentials",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_slug": {"type": "string", "description": "Workspace slug"},
                "integration_slug": {"type": "string", "description": "Integration slug"},
                "credentials": {"type": "object", "description": "Credentials (e.g. {token, username, api_key})"},
                "external_id": {"type": "string", "description": "External project/entity ID for auto-injection"},
                "base_url_override": {"type": "string", "description": "Override base URL"},
            },
            "required": ["workspace_slug", "integration_slug", "credentials"],
        },
    },
    {
        "name": "connection_test",
        "description": "Test a connection by calling the first read tool",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_slug": {"type": "string", "description": "Workspace slug"},
                "integration_slug": {"type": "string", "description": "Integration slug"},
            },
            "required": ["workspace_slug", "integration_slug"],
        },
    },
    {
        "name": "workspace_list",
        "description": "List all workspaces",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "workspace_create",
        "description": "Create a new workspace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Workspace name"},
                "slug": {"type": "string", "description": "Workspace slug (URL-safe)"},
            },
            "required": ["name", "slug"],
        },
    },
]


async def execute_meta_tool(
    tool_name: str,
    arguments: dict[str, Any],
    session: MCPSession,
    db: AsyncSession,
) -> dict[str, Any]:
    """Execute a meta-tool and return the result."""
    handlers = {
        "integration_list": _integration_list,
        "integration_inspect": _integration_inspect,
        "integration_create": _integration_create,
        "integration_create_from_openapi": _integration_create_from_openapi,
        "integration_delete": _integration_delete,
        "connection_create": _connection_create,
        "connection_test": _connection_test,
        "workspace_list": _workspace_list,
        "workspace_create": _workspace_create,
    }

    handler = handlers.get(tool_name)
    if not handler:
        return {"error": f"Unknown meta-tool: {tool_name}"}

    return await handler(arguments, session, db)


async def _integration_list(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    result = await db.execute(
        select(Integration).where(
            Integration.is_active == True,  # noqa: E712
            or_(
                Integration.scope == "public",
                Integration.account_id == session.account_id,
            ),
        )
    )
    integrations = result.scalars().all()
    return {
        "integrations": [
            {"slug": i.slug, "name": i.name, "category": i.category, "scope": i.scope}
            for i in integrations
        ]
    }


async def _integration_inspect(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    slug = args.get("slug")
    result = await db.execute(
        select(Integration)
        .options(selectinload(Integration.tools))
        .where(Integration.slug == slug)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        return {"error": f"Integration '{slug}' not found"}

    return {
        "slug": integration.slug,
        "name": integration.name,
        "base_url": integration.base_url,
        "auth_config": integration.auth_config,
        "tools": [
            {"slug": t.slug, "name": t.name, "method": t.method, "path": t.path, "tool_type": t.tool_type}
            for t in integration.tools
        ],
    }


async def _integration_create(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    spec = args.get("spec", {})
    slug = spec.get("slug")
    if not slug:
        return {"error": "spec.slug is required"}

    integration = Integration(
        slug=slug,
        name=spec.get("name", slug),
        description=spec.get("description", ""),
        category=spec.get("category", "other"),
        base_url=spec.get("base_url", ""),
        auth_config=spec.get("auth_config", {}),
        variables=spec.get("variables", {}),
        scope="private",
        account_id=session.account_id,
        source_spec_url=spec.get("source_spec_url"),
    )
    db.add(integration)
    await db.flush()

    for tool_spec in spec.get("tools", []):
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
    return {"status": "created", "slug": slug, "tools_count": len(spec.get("tools", []))}


async def _integration_create_from_openapi(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    url = args.get("url")
    if not url:
        return {"error": "url is required"}

    from ..openapi_import.parser import parse_openapi_url
    try:
        spec = await parse_openapi_url(url)
    except Exception as e:
        return {"error": f"Failed to parse OpenAPI spec: {e}"}

    spec["source_spec_url"] = url
    return await _integration_create({"spec": spec}, session, db)


async def _integration_delete(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    slug = args.get("slug")
    result = await db.execute(
        select(Integration).where(
            Integration.slug == slug,
            Integration.scope == "private",
            Integration.account_id == session.account_id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        return {"error": f"Private integration '{slug}' not found"}

    await db.delete(integration)
    await db.commit()
    return {"status": "deleted", "slug": slug}


async def _connection_create(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    ws_slug = args.get("workspace_slug")
    int_slug = args.get("integration_slug")
    creds = args.get("credentials", {})

    # Find workspace
    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == session.account_id,
            Workspace.slug == ws_slug,
        )
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        return {"error": f"Workspace '{ws_slug}' not found"}

    # Find integration
    result = await db.execute(
        select(Integration).where(Integration.slug == int_slug, Integration.is_active == True)  # noqa: E712
    )
    integration = result.scalar_one_or_none()
    if not integration:
        return {"error": f"Integration '{int_slug}' not found"}

    # Encrypt credentials
    encrypted_creds = {}
    for k, v in creds.items():
        encrypted_creds[k] = encrypt_value(v) if isinstance(v, str) and v else v

    conn = Connection(
        workspace_id=workspace.id,
        integration_id=integration.id,
        credentials=encrypted_creds,
        external_id=args.get("external_id"),
        base_url_override=args.get("base_url_override"),
    )
    db.add(conn)
    await db.commit()

    return {"status": "created", "workspace": ws_slug, "integration": int_slug}


async def _connection_test(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    ws_slug = args.get("workspace_slug")
    int_slug = args.get("integration_slug")

    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == session.account_id,
            Workspace.slug == ws_slug,
        )
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        return {"error": f"Workspace '{ws_slug}' not found"}

    result = await db.execute(
        select(Connection)
        .join(Integration)
        .where(
            Connection.workspace_id == workspace.id,
            Integration.slug == int_slug,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return {"error": f"Connection not found for {int_slug} in {ws_slug}"}

    result = await db.execute(
        select(Integration).options(selectinload(Integration.tools)).where(Integration.slug == int_slug)
    )
    integration = result.scalar_one_or_none()

    # Find first read tool
    read_tool = None
    for tool in integration.tools:
        if tool.tool_type == "read" and tool.is_enabled:
            read_tool = tool
            break

    if not read_tool:
        return {"error": "No read tool available for testing"}

    from ..executor.engine import execute_tool
    result = await execute_tool(
        tool=read_tool, integration=integration, connection=conn, params={}, db=db,
    )

    if "error" in result:
        conn.is_verified = False
        conn.last_error = result["error"]
        await db.commit()
        return {"status": "failed", "error": result["error"]}

    conn.is_verified = True
    conn.last_error = None
    await db.commit()
    return {"status": "ok", "tool_tested": f"{integration.slug}_{read_tool.slug}"}


async def _workspace_list(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    result = await db.execute(
        select(Workspace).where(
            Workspace.account_id == session.account_id,
            Workspace.is_active == True,  # noqa: E712
        )
    )
    workspaces = result.scalars().all()
    return {
        "workspaces": [{"slug": w.slug, "name": w.name} for w in workspaces]
    }


async def _workspace_create(args: dict, session: MCPSession, db: AsyncSession) -> dict:
    name = args.get("name")
    slug = args.get("slug")
    if not name or not slug:
        return {"error": "name and slug are required"}

    ws = Workspace(account_id=session.account_id, name=name, slug=slug)
    db.add(ws)
    await db.commit()
    return {"status": "created", "slug": slug}
