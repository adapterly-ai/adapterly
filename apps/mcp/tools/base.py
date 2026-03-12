"""
Base classes and utilities for MCP tools.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """
    Represents an MCP tool definition.

    Attributes:
        name: Unique tool identifier (e.g., 'salesforce_contact_create')
        description: Human-readable description for documentation
        llm_description: Shorter, LLM-optimized description for AI agents (optional)
        tool_hints: Usage hints and guidance specifically for AI agents
        input_schema: JSON Schema defining tool parameters
        handler: Async function that executes the tool
        tool_type: Category for permission filtering
        examples: Usage examples with input/output pairs
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable
    tool_type: str = "system_read"  # system_read, system_write, context, resource

    # LLM-optimized metadata
    llm_description: str | None = None  # Shorter description optimized for LLMs
    tool_hints: str | None = None  # Usage guidance for AI agents

    # Optional metadata
    output_schema: dict[str, Any] | None = None
    examples: list[dict[str, Any]] = field(default_factory=list)
    system_alias: str | None = None
    action_alias: str | None = None

    def to_mcp_format(self, for_llm: bool = True) -> dict[str, Any]:
        """
        Convert to MCP protocol format.

        Args:
            for_llm: If True, prefer LLM-optimized descriptions and include hints
        """
        # Use LLM description if available and requested, otherwise fall back to standard
        description = self.description
        if for_llm and self.llm_description:
            description = self.llm_description

        # Append tool hints for LLM consumption
        if for_llm and self.tool_hints:
            description = f"{description}\n\nUsage hints: {self.tool_hints}"

        result = {
            "name": self.name,
            "description": description,
            "inputSchema": self.input_schema,
        }

        # Include examples if available (helpful for LLMs)
        if for_llm and self.examples:
            result["examples"] = self.examples

        return result


class MCPToolRegistry:
    """
    Registry for MCP tools.

    Manages tool registration, discovery, and filtering based on permissions.
    """

    def __init__(self):
        self._tools: dict[str, MCPTool] = {}

    def register(self, tool: MCPTool):
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered MCP tool: {tool.name}")

    def unregister(self, name: str):
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> MCPTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(
        self,
        include_write: bool = True,
        allowed_patterns: list[str] | None = None,
        blocked_patterns: list[str] | None = None,
        profile: Any | None = None,
    ) -> list[MCPTool]:
        """
        List available tools with optional filtering.

        Args:
            include_write: Whether to include write tools
            allowed_patterns: fnmatch patterns for allowed tools
            blocked_patterns: fnmatch patterns for blocked tools
            profile: Optional AgentProfile for tool filtering

        Returns:
            List of MCPTool objects
        """
        import fnmatch

        tools = []
        for name, tool in self._tools.items():
            # Filter by write permission
            if not include_write and tool.tool_type == "system_write":
                continue

            # Check blocked patterns
            if blocked_patterns:
                if any(fnmatch.fnmatch(name, p) for p in blocked_patterns):
                    continue

            # Check allowed patterns (if specified, only allow matching)
            if allowed_patterns:
                if not any(fnmatch.fnmatch(name, p) for p in allowed_patterns):
                    continue

            # Check profile restrictions
            if profile and not profile.is_tool_allowed(name):
                continue

            tools.append(tool)

        return tools

    def list_tools_mcp_format(self, for_llm: bool = True, **kwargs) -> list[dict[str, Any]]:
        """
        List tools in MCP protocol format.

        Args:
            for_llm: If True, use LLM-optimized descriptions and include hints
            **kwargs: Filter options passed to list_tools()
        """
        tools = self.list_tools(**kwargs)
        return [t.to_mcp_format(for_llm=for_llm) for t in tools]

    def clear(self):
        """Clear all registered tools."""
        self._tools.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def build_input_schema(properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    """
    Build a JSON Schema for tool input.

    Args:
        properties: Dict of property name -> schema
        required: List of required property names

    Returns:
        JSON Schema dict
    """
    schema = {
        "type": "object",
        "properties": properties,
    }

    if required:
        schema["required"] = required

    return schema


def mcp_tool(name: str, description: str, input_schema: dict[str, Any], tool_type: str = "system_read", **kwargs):
    """
    Decorator to mark a function as an MCP tool.

    Usage:
        @mcp_tool(
            name="salesforce_contact_list",
            description="List Salesforce contacts",
            input_schema={...},
            tool_type="system_read"
        )
        async def salesforce_contact_list(ctx, filters=None):
            ...
    """

    def decorator(func):
        func._mcp_tool = MCPTool(
            name=name, description=description, input_schema=input_schema, handler=func, tool_type=tool_type, **kwargs
        )
        return func

    return decorator


def get_tools_from_module(module) -> list[MCPTool]:
    """
    Extract MCP tools from a module.

    Looks for functions decorated with @mcp_tool.
    """
    tools = []
    for name in dir(module):
        obj = getattr(module, name)
        if callable(obj) and hasattr(obj, "_mcp_tool"):
            tools.append(obj._mcp_tool)
    return tools
