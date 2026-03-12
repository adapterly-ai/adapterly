"""
MCP Resources module.

Provides read-only context through MCP resources:
- systems:// - Available systems and their schemas
"""

from apps.mcp.resources.systems import get_system_resources

__all__ = [
    "get_system_resources",
]
