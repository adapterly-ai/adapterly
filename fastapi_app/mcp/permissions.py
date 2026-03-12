"""
MCP Permission system - async implementation.

Simple model: mode (safe/power) + allowed_tools (JSON list on MCPApiKey).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.mcp import MCPApiKey, Project

logger = logging.getLogger(__name__)


class MCPPermissionChecker:
    """
    Permission checker for MCP tool calls.

    Rules:
    1. Admin + system_read/system_write -> DENY
    2. Non-system tool (context, management, resource) -> ALLOW always
    3. system_write + mode=="safe" -> DENY
    4. allowed_tools non-empty AND tool_name not in list -> DENY
    5. Otherwise -> ALLOW
    """

    def __init__(
        self,
        account_id: int,
        mode: str = "safe",
        is_admin: bool = False,
        allowed_tools: list[str] | None = None,
    ):
        self.account_id = account_id
        self.mode = mode.lower()
        self.is_admin = is_admin
        self.allowed_tools = allowed_tools or []

        if self.mode not in ("safe", "power"):
            raise ValueError(f"Invalid mode: {mode}")

    @classmethod
    async def create(
        cls,
        account_id: int,
        api_key_id: int | None = None,
        is_admin: bool = False,
        mode: str | None = None,
        project: Project | None = None,
        user_id: int | None = None,
        db: AsyncSession | None = None,
    ) -> "MCPPermissionChecker":
        """
        Create permission checker with data loaded from database.
        Reads mode and allowed_tools directly from MCPApiKey.
        """
        resolved_mode = mode or "safe"
        allowed_tools = []

        if db and api_key_id:
            stmt = select(MCPApiKey).where(MCPApiKey.id == api_key_id)
            result = await db.execute(stmt)
            api_key = result.scalar_one_or_none()

            if api_key:
                if not mode:
                    resolved_mode = api_key.mode
                allowed_tools = api_key.allowed_tools or []

        return cls(
            account_id=account_id,
            mode=resolved_mode,
            is_admin=is_admin,
            allowed_tools=allowed_tools,
        )

    def is_tool_allowed(self, tool_name: str, tool_type: str) -> bool:
        """
        Check if a tool is allowed.

        Args:
            tool_name: Name of the tool
            tool_type: Type of tool (system_read, system_write, context, management, resource)

        Returns:
            True if allowed
        """
        # 1. Admin tokens cannot call system tools
        if self.is_admin and tool_type in ("system_read", "system_write"):
            return False

        # 2. Non-system tools are always allowed
        if tool_type not in ("system_read", "system_write"):
            return True

        # 3. Safe mode blocks write operations
        if tool_type == "system_write" and self.mode == "safe":
            return False

        # 4. If allowed_tools is non-empty, tool must be in the list
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return False

        # 5. Allow
        return True
