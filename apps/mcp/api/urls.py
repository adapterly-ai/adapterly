"""
URL configuration for MCP API.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.mcp.api.views import (
    AgentProfileViewSet,
    MCPApiKeyViewSet,
    MCPAuditLogViewSet,
    MCPSessionViewSet,
    ProjectIntegrationViewSet,
    ProjectViewSet,
)

router = DefaultRouter()
router.register(r"agent-profiles", AgentProfileViewSet, basename="mcp-agent-profile")
router.register(r"api-keys", MCPApiKeyViewSet, basename="mcp-api-key")
router.register(r"sessions", MCPSessionViewSet, basename="mcp-session")
router.register(r"audit-logs", MCPAuditLogViewSet, basename="mcp-audit-log")
router.register(r"projects", ProjectViewSet, basename="mcp-project")
router.register(r"project-integrations", ProjectIntegrationViewSet, basename="mcp-project-integration")

app_name = "mcp-api"

urlpatterns = [
    path("", include(router.urls)),
]
