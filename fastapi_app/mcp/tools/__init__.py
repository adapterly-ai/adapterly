"""
MCP Tools module.

Provides tool definitions for the MCP server.
Adapterly focuses on being an MCP Tool Gateway - system connections,
permissions, audit logging, and project mapping.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .systems import execute_system_tool, get_system_tools

logger = logging.getLogger(__name__)


async def get_all_tools(
    account_id: int, db: AsyncSession | None = None, project_id: int | None = None
) -> list[dict[str, Any]]:
    """
    Get all available tools for an account.

    Returns system tools from configured integrations.

    Args:
        account_id: Account ID
        db: Database session
        project_id: Optional project ID for scoping system tools

    Returns:
        List of tool definitions
    """
    tools = []

    # Add system tools from database
    if db:
        try:
            system_tools = await get_system_tools(db, account_id, project_id=project_id)
            for tool_def in system_tools:
                # Create handler closure for this tool
                action_id = tool_def["action_id"]
                handler = create_system_tool_handler(action_id)
                tool_def["handler"] = handler
                tools.append(tool_def)
            logger.info(f"Loaded {len(system_tools)} system tools for account {account_id}")
        except Exception as e:
            logger.warning(f"Error loading system tools: {e}")

    return tools


def create_system_tool_handler(action_id: int):
    """Create a handler function for a system tool."""

    async def handler(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
        db = ctx.get("db")
        account_id = ctx.get("account_id")
        project_id = ctx.get("project_id")

        if not db:
            return {"error": "Database session not available"}

        return await execute_system_tool(db, action_id, account_id, kwargs, project_id=project_id)

    return handler
