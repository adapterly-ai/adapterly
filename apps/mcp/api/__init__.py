"""
MCP API module.

Provides REST API endpoints for managing MCP resources:
- API keys
- Sessions
- Audit logs
"""

from apps.mcp.api.serializers import (
    MCPApiKeyCreateSerializer,
    MCPApiKeySerializer,
    MCPAuditLogSerializer,
    MCPSessionSerializer,
)
from apps.mcp.api.views import (
    MCPApiKeyViewSet,
    MCPAuditLogViewSet,
    MCPSessionViewSet,
)

__all__ = [
    "MCPApiKeyViewSet",
    "MCPSessionViewSet",
    "MCPAuditLogViewSet",
    "MCPApiKeySerializer",
    "MCPApiKeyCreateSerializer",
    "MCPSessionSerializer",
    "MCPAuditLogSerializer",
]
