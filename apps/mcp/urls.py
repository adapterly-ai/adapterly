"""
URL configuration for MCP user-facing pages.

Note: REST API is available at /api/mcp/ (configured in config/urls.py)
"""

from django.urls import path

from apps.mcp import views

app_name = "mcp"

urlpatterns = [
    # User-facing pages
    path("", views.mcp_dashboard, name="dashboard"),
    path("tools/", views.mcp_tools, name="tools"),
    path("api-keys/", views.mcp_api_keys, name="api_keys"),
    path("logs/", views.mcp_logs, name="logs"),
    path("logs/<int:log_id>/", views.mcp_log_detail, name="log_detail"),
    path("sessions/", views.mcp_sessions, name="sessions"),
    # Agent Profiles
    path("profiles/", views.agent_profiles, name="profiles"),
    path("profiles/create/", views.agent_profile_create, name="profile_create"),
    path("profiles/<int:profile_id>/edit/", views.agent_profile_edit, name="profile_edit"),
    path("profiles/<int:profile_id>/delete/", views.agent_profile_delete, name="profile_delete"),
    # API Key Edit & Test
    path("api-keys/<int:key_id>/edit/", views.api_key_edit, name="api_key_edit"),
    path("api-keys/<int:key_id>/test/", views.api_key_test, name="api_key_test"),
    # AJAX actions
    path("api-keys/create/", views.mcp_create_api_key, name="create_api_key"),
    path("api-keys/update/", views.mcp_update_api_key, name="update_api_key"),
    path("api-keys/delete/", views.mcp_delete_api_key, name="delete_api_key"),
    path("api-keys/toggle/", views.mcp_toggle_api_key, name="toggle_api_key"),
    # Project Tools (AJAX)
    path("projects/<int:project_id>/tools/", views.project_tools_json, name="project_tools_json"),
    # Project Integrations
    path("projects/<int:project_id>/integrations/", views.project_integrations, name="project_integrations"),
    path("projects/<int:project_id>/integrations/add/", views.project_integration_add, name="project_integration_add"),
    path(
        "projects/<int:project_id>/integrations/<int:integration_id>/edit/",
        views.project_integration_edit,
        name="project_integration_edit",
    ),
    path(
        "projects/<int:project_id>/integrations/<int:integration_id>/remove/",
        views.project_integration_remove,
        name="project_integration_remove",
    ),
]
