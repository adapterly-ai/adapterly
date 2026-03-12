"""
MCP Transport module.

Provides transport implementations for the MCP server:
- stdio: Standard I/O transport for CLI usage (Claude Code)
- sse: Server-Sent Events transport for web usage (Claude.ai)
"""

from apps.mcp.transports.sse import SSETransport
from apps.mcp.transports.stdio import StdioTransport

__all__ = [
    "StdioTransport",
    "SSETransport",
]
