"""MCP permission model: mode + whitelist + blacklist."""


class PermissionChecker:
    """
    Three checks in order:
    1. Mode: safe → block write tools. power → allow all.
    2. Whitelist: allowed_tools non-empty → only these visible.
    3. Blacklist: blocked_tools → always hidden.
    """

    def __init__(
        self,
        mode: str = "safe",
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
    ):
        self.mode = mode.lower()
        self.allowed_tools = set(allowed_tools or [])
        self.blocked_tools = set(blocked_tools or [])

    def is_allowed(self, tool_name: str, tool_type: str) -> bool:
        # 1. Blacklist always wins
        if tool_name in self.blocked_tools:
            return False

        # 2. Safe mode blocks write tools
        if self.mode == "safe" and tool_type == "write":
            return False

        # 3. Whitelist check
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return False

        return True
