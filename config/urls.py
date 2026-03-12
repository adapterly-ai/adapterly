"""
URL configuration for Adapterly - MCP Tool Gateway.

Routes for system connections, MCP protocol, and administration.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

from apps.mcp.api.transport import mcp_endpoint
from apps.oauth.urls import wellknown_urlpatterns


def health_check(request):
    return JsonResponse({"status": "healthy"})


urlpatterns = [
    path("health/", health_check, name="health-check"),
    # Admin
    path("admin/", admin.site.urls),
    # Authentication
    path("auth/", include("allauth.urls")),
    # Token auth (username + password -> token)
    path("api/auth/token/", obtain_auth_token, name="api-token-auth"),
    # Core (landing, dashboard)
    path("", include("apps.core.urls")),
    # Account management
    path("account/", include("apps.accounts.urls")),
    # Systems (adapters, integrations)
    path("systems/", include("apps.systems.urls")),
    # Help
    path("help/", include("apps.help.urls")),
    # Projects
    path("projects/", include("apps.mcp.project_urls")),
    # MCP Gateway
    path("mcp/", include("apps.mcp.urls")),
    path("mcp/v1/", mcp_endpoint, name="mcp-protocol"),  # MCP Streamable HTTP
    # API endpoints
    path("api/", include("apps.accounts.api.urls")),
    path("api/mcp/", include("apps.mcp.api.urls")),
    path("api/systems/", include("apps.systems.api.urls")),
    # Gateway Sync API (control plane)
    path("gateway-sync/v1/", include("apps.gateways.urls")),
    # Tools REST API (CLI / scripting)
    path("api/v1/tools/", include("apps.mcp.api.tool_urls")),
    # OAuth2 Provider
    path("oauth/", include("apps.oauth.urls")),
] + wellknown_urlpatterns

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
