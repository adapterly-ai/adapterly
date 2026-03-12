from django.apps import AppConfig


class MCPConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mcp"
    verbose_name = "MCP Gateway"

    def ready(self):
        # Import signal handlers if any
        pass
