"""
Gateway Core - Shared execution engine for Adapterly MCP gateways.

This package contains the core logic for executing system tool calls,
managing credentials, and handling authentication. It is designed to
work independently of Django, using only SQLAlchemy and standard libs.

Used by:
- fastapi_app (monolith mode): imports gateway_core for tool execution
- adapterly-gateway (standalone mode): uses gateway_core with local SQLite
"""

__version__ = "0.1.0"
