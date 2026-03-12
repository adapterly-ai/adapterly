"""
MCP Permission system with Safe/Power mode support and profile-based access control.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.mcp.models import AgentProfile

logger = logging.getLogger(__name__)


@dataclass
class PermissionResult:
    """Result of a permission check."""

    allowed: bool
    reason: str = ""


class MCPPermissionChecker:
    """
    Permission checker for MCP tool calls.

    Supports two modes:
    - Safe Mode: Only read operations allowed
    - Power Mode: All operations allowed based on tool-specific permissions

    Also supports profile-based access control via AgentProfile.include_tools.
    """

    def __init__(
        self,
        account_id: int,
        mode: str = "safe",
        allowed_tools: list | None = None,
        blocked_tools: list | None = None,
        profile: AgentProfile | None = None,
    ):
        """
        Initialize permission checker.

        Args:
            account_id: The account ID to check permissions for
            mode: Either "safe" or "power"
            allowed_tools: List of allowed tool patterns (fnmatch)
            blocked_tools: List of blocked tool patterns (fnmatch)
            profile: Optional AgentProfile for profile-based access control
        """
        self.account_id = account_id
        self.mode = mode.lower()
        self.allowed_tools = allowed_tools or []
        self.blocked_tools = blocked_tools or []
        self.profile = profile

        if self.mode not in ("safe", "power"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'safe' or 'power'")

    def can_call_tool(self, tool_name: str, tool_type: str) -> PermissionResult:
        """
        Check if a tool call is allowed.

        Args:
            tool_name: Name of the tool (e.g., "salesforce_contact_create")
            tool_type: Type of tool - one of:
                - "system_read": System read operations
                - "system_write": System write operations
                - "resource": Resource access (read-only)
                - "context": Context management tools

        Returns:
            PermissionResult with allowed status and reason
        """
        # Check blocked tools first (from profile or direct)
        if self._matches_patterns(tool_name, self.blocked_tools):
            return PermissionResult(allowed=False, reason=f"Tool '{tool_name}' is explicitly blocked")

        # Check profile-based restrictions (if profile exists)
        if self.profile and not self.profile.is_tool_allowed(tool_name):
            return PermissionResult(
                allowed=False, reason=f"Tool '{tool_name}' not allowed by profile '{self.profile.name}'"
            )

        # Resource access (read-only) is always allowed
        if tool_type == "resource":
            return PermissionResult(allowed=True)

        # System read operations are always allowed
        if tool_type == "system_read":
            return PermissionResult(allowed=True)

        # System write operations depend on mode
        if tool_type == "system_write":
            if self.mode == "safe":
                return PermissionResult(allowed=False, reason="Write operations require Power Mode in Safe Mode")
            else:
                # Power mode - check specific permissions
                return self._check_tool_permission(tool_name)

        # Unknown tool type - deny by default
        return PermissionResult(allowed=False, reason=f"Unknown tool type: {tool_type}")

    def _check_tool_permission(self, tool_name: str) -> PermissionResult:
        """
        Check tool-specific permissions in Power Mode.
        """
        # If allowed_tools is empty, all non-blocked tools are allowed
        if not self.allowed_tools:
            return PermissionResult(allowed=True)

        # Check if tool matches any allowed pattern
        if self._matches_patterns(tool_name, self.allowed_tools):
            return PermissionResult(allowed=True)

        return PermissionResult(allowed=False, reason=f"Tool '{tool_name}' not in allowed list")

    def _matches_patterns(self, tool_name: str, patterns: list) -> bool:
        """Check if tool name matches any pattern."""
        for pattern in patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
        return False

    def get_tool_list_filter(self) -> dict:
        """
        Get filter for listing available tools.

        Returns dict with:
            - include_write: Whether to include write tools
            - allowed_patterns: Patterns to include
            - blocked_patterns: Patterns to exclude
            - profile: AgentProfile for tool filtering
        """
        return {
            "include_write": self.mode == "power",
            "allowed_patterns": self.allowed_tools,
            "blocked_patterns": self.blocked_tools,
            "profile": self.profile,
        }


def get_permission_checker(
    account_id: int,
    api_key: str | None = None,
    mode: str | None = None,
    user_id: int | None = None,
) -> MCPPermissionChecker:
    """
    Factory function to create a permission checker.

    Args:
        account_id: Account ID
        api_key: Optional API key to load permissions from
        mode: Override mode (if not specified, uses API key's mode or 'safe')
        user_id: Optional user ID

    Returns:
        Configured MCPPermissionChecker
    """
    from apps.mcp.models import MCPApiKey

    allowed_tools = []
    blocked_tools = []
    resolved_mode = mode or "safe"
    profile = None

    if api_key:
        try:
            # Find matching API key
            prefix = api_key[:10] if len(api_key) >= 10 else api_key
            key_obj = (
                MCPApiKey.objects.select_related("profile")
                .filter(account_id=account_id, key_prefix=prefix, is_active=True)
                .first()
            )

            if key_obj and key_obj.check_key(api_key):
                key_obj.mark_used()

                # Check if API key has a profile
                if key_obj.profile and key_obj.profile.is_active:
                    profile = key_obj.profile
                    if not mode:
                        resolved_mode = profile.mode
                else:
                    # Legacy: use API key's direct settings
                    if not mode:
                        resolved_mode = key_obj.mode
                    allowed_tools = key_obj.allowed_tools or []
                    blocked_tools = key_obj.blocked_tools or []
        except Exception as e:
            logger.warning(f"Failed to load API key permissions: {e}")

    return MCPPermissionChecker(
        account_id=account_id,
        mode=resolved_mode,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        profile=profile,
    )
