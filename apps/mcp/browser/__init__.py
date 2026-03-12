"""
MCP Browser module.

Provides browser automation for XHR-based system integrations.
Uses Playwright for session management and login flows.
"""

from apps.mcp.browser.session import BrowserSessionManager, LoginResult

__all__ = [
    "BrowserSessionManager",
    "LoginResult",
]
