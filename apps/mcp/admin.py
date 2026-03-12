"""
Django Admin configuration for MCP models.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from apps.mcp.models import (
    AgentProfile,
    ErrorDiagnostic,
    MCPApiKey,
    MCPAuditLog,
    MCPSession,
    Project,
    ProjectIntegration,
)


@admin.register(MCPAuditLog)
class MCPAuditLogAdmin(admin.ModelAdmin):
    """Admin for MCP audit logs."""

    list_display = [
        "timestamp",
        "account",
        "tool_name",
        "tool_type",
        "success_badge",
        "duration_ms",
        "mode",
        "transport",
    ]
    list_filter = ["success", "tool_type", "mode", "transport", "timestamp", "account"]
    search_fields = ["tool_name", "session_id", "error_message"]
    readonly_fields = [
        "account",
        "user",
        "tool_name",
        "tool_type",
        "parameters",
        "result_summary",
        "duration_ms",
        "success",
        "error_message",
        "session_id",
        "transport",
        "mode",
        "timestamp",
    ]
    ordering = ["-timestamp"]
    date_hierarchy = "timestamp"

    def success_badge(self, obj):
        if obj.success:
            return format_html('<span style="color: green; font-weight: bold;">✓</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗</span>')

    success_badge.short_description = "OK"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Allow superusers to delete old logs
        return request.user.is_superuser


@admin.register(MCPSession)
class MCPSessionAdmin(admin.ModelAdmin):
    """Admin for MCP sessions."""

    list_display = [
        "session_id_short",
        "account",
        "user",
        "mode",
        "transport",
        "is_active",
        "tool_calls_count",
        "last_activity",
    ]
    list_filter = ["is_active", "mode", "transport", "account"]
    search_fields = ["session_id", "user__username"]
    readonly_fields = ["session_id", "created_at", "last_activity", "tool_calls_count"]
    ordering = ["-last_activity"]

    def session_id_short(self, obj):
        return f"{obj.session_id[:16]}..."

    session_id_short.short_description = "Session ID"

    actions = ["deactivate_sessions"]

    @admin.action(description="Deactivate selected sessions")
    def deactivate_sessions(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} sessions deactivated.")


@admin.register(MCPApiKey)
class MCPApiKeyAdmin(admin.ModelAdmin):
    """Admin for MCP API keys."""

    list_display = [
        "name",
        "account",
        "key_prefix",
        "project_link",
        "is_admin_badge",
        "mode",
        "is_active",
        "last_used_at",
        "expires_status",
        "created_at",
    ]
    list_filter = ["is_active", "is_admin", "mode", "project", "account"]
    search_fields = ["name", "key_prefix", "project__slug", "project__name"]
    readonly_fields = ["key_prefix", "key_hash", "created_at", "last_used_at"]
    ordering = ["-created_at"]
    autocomplete_fields = ["project", "profile"]

    fieldsets = (
        (None, {"fields": ("name", "account", "created_by")}),
        (
            "Key Info",
            {"fields": ("key_prefix", "key_hash"), "description": "The full API key is only shown once when created."},
        ),
        (
            "Project Binding",
            {
                "fields": ("project", "is_admin"),
                "description": "Bind token to a project. Admin tokens are for management only.",
            },
        ),
        ("Permissions", {"fields": ("profile", "mode", "allowed_tools", "blocked_tools")}),
        ("Status", {"fields": ("is_active", "expires_at", "last_used_at", "created_at")}),
    )

    def project_link(self, obj):
        if obj.project:
            return format_html('<a href="/admin/mcp/project/{}/change/">{}</a>', obj.project.id, obj.project.slug)
        return format_html('<span style="color: gray;">—</span>')

    project_link.short_description = "Project"

    def is_admin_badge(self, obj):
        if obj.is_admin:
            return format_html('<span style="color: orange; font-weight: bold;">Admin</span>')
        return format_html('<span style="color: gray;">—</span>')

    is_admin_badge.short_description = "Admin"

    def expires_status(self, obj):
        if not obj.expires_at:
            return format_html('<span style="color: gray;">Never</span>')
        if obj.expires_at < timezone.now():
            return format_html('<span style="color: red;">Expired</span>')
        return format_html('<span style="color: green;">Valid</span>')

    expires_status.short_description = "Expires"

    actions = ["deactivate_keys", "activate_keys"]

    @admin.action(description="Deactivate selected API keys")
    def deactivate_keys(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} API keys deactivated.")

    @admin.action(description="Activate selected API keys")
    def activate_keys(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} API keys activated.")


class ProjectIntegrationInline(admin.TabularInline):
    """Inline admin for project integrations."""

    model = ProjectIntegration
    extra = 0
    fields = ["system", "external_id", "is_enabled", "notes"]
    autocomplete_fields = ["system"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin for MCP Projects."""

    list_display = [
        "name",
        "slug",
        "account",
        "mapping_summary",
        "api_key_count",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "account"]
    search_fields = ["name", "slug", "description", "external_mappings"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["name"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProjectIntegrationInline]

    fieldsets = (
        (None, {"fields": ("account", "name", "slug", "description")}),
        (
            "External System Mappings",
            {
                "fields": ("external_mappings",),
                "description": 'JSON mapping of system aliases to external IDs. Example: {"jira": "PROJ-123", "github": "org/repo"}',
            },
        ),
        ("Status", {"fields": ("is_active", "created_at", "updated_at")}),
    )

    def mapping_summary(self, obj):
        if not obj.external_mappings:
            return format_html('<span style="color: gray;">None</span>')
        systems = list(obj.external_mappings.keys())
        if len(systems) <= 3:
            return ", ".join(systems)
        return f"{', '.join(systems[:3])}... (+{len(systems) - 3})"

    mapping_summary.short_description = "Systems"

    def api_key_count(self, obj):
        count = obj.api_keys.count()
        if count == 0:
            return format_html('<span style="color: gray;">0</span>')
        return count

    api_key_count.short_description = "API Keys"


@admin.register(ProjectIntegration)
class ProjectIntegrationAdmin(admin.ModelAdmin):
    """Admin for project integrations."""

    list_display = [
        "project",
        "system",
        "credential_status_badge",
        "external_id_short",
        "is_enabled",
        "created_at",
    ]
    list_filter = [
        "is_enabled",
        "project__account",
    ]
    search_fields = [
        "project__name",
        "project__slug",
        "system__alias",
        "system__display_name",
        "external_id",
    ]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project__name", "system__alias"]
    autocomplete_fields = ["project", "system"]

    fieldsets = (
        (None, {"fields": ("project", "system")}),
        ("Configuration", {"fields": ("external_id", "is_enabled", "custom_config", "notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ["test_connection"]

    def external_id_short(self, obj):
        if not obj.external_id:
            return format_html('<span style="color: gray;">-</span>')
        text = obj.external_id
        if len(text) > 40:
            return text[:37] + "..."
        return text

    external_id_short.short_description = "External ID"

    def _get_account_system(self, integration):
        """Find the matching AccountSystem for an integration (always workspace-level)."""
        from apps.systems.models import AccountSystem

        return AccountSystem.objects.filter(
            account=integration.project.account,
            system=integration.system,
            project=integration.project,
        ).first()

    def credential_status_badge(self, obj):
        accsys = self._get_account_system(obj)
        if accsys is None:
            return format_html('<span style="color: gray;">No credentials</span>')
        if accsys.is_verified:
            return format_html('<span style="color: green; font-weight: bold;">Verified</span>')
        if accsys.last_error:
            return format_html('<span style="color: red;" title="{}">Error</span>', accsys.last_error)
        return format_html('<span style="color: orange;">Not verified</span>')

    credential_status_badge.short_description = "Credentials"

    @admin.action(description="Test connection for selected integrations")
    def test_connection(self, request, queryset):
        from apps.systems.services import test_system_connection

        for integration in queryset.select_related("project__account", "system"):
            accsys = self._get_account_system(integration)
            if accsys is None:
                self.message_user(
                    request,
                    f"{integration.project.slug}/{integration.system.alias}: No credentials configured",
                    level="warning",
                )
                continue

            success, message = test_system_connection(accsys)
            if success:
                accsys.mark_verified()
                self.message_user(
                    request,
                    f"{integration.project.slug}/{integration.system.alias}: {message}",
                )
            else:
                accsys.mark_error(message)
                self.message_user(
                    request,
                    f"{integration.project.slug}/{integration.system.alias}: {message}",
                    level="error",
                )


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    """Admin for agent profiles."""

    list_display = ["name", "project", "account", "mode", "tool_count", "api_key_count", "is_active", "created_at"]
    list_filter = ["is_active", "mode", "account", "project"]
    search_fields = ["name", "description", "project__name", "project__slug"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["name"]
    autocomplete_fields = ["project"]

    fieldsets = (
        (None, {"fields": ("account", "project", "name", "description")}),
        ("Permissions", {"fields": ("mode", "include_tools")}),
        ("Status", {"fields": ("is_active", "created_at", "updated_at")}),
    )

    def tool_count(self, obj):
        if not obj.include_tools:
            return format_html('<span style="color: green;">All</span>')
        return f"{len(obj.include_tools)} tools"

    tool_count.short_description = "Tools"

    def api_key_count(self, obj):
        return obj.api_keys.count()

    api_key_count.short_description = "API Keys"


@admin.register(ErrorDiagnostic)
class ErrorDiagnosticAdmin(admin.ModelAdmin):
    """Admin for error diagnostics."""

    list_display = [
        "created_at",
        "system_alias",
        "category_badge",
        "severity_badge",
        "summary_short",
        "status_badge",
        "occurrence_count",
        "has_fix_badge",
    ]
    list_filter = [
        "status",
        "category",
        "severity",
        "system_alias",
        "has_fix",
        "account",
    ]
    search_fields = [
        "system_alias",
        "tool_name",
        "error_message",
        "diagnosis_summary",
    ]
    readonly_fields = [
        "account",
        "system_alias",
        "tool_name",
        "action_name",
        "status_code",
        "error_message",
        "error_data",
        "category",
        "severity",
        "diagnosis_summary",
        "diagnosis_detail",
        "has_fix",
        "fix_description",
        "fix_action",
        "occurrence_count",
        "first_seen_at",
        "last_seen_at",
        "created_at",
    ]
    ordering = ["-last_seen_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Error",
            {
                "fields": (
                    "account",
                    "system_alias",
                    "tool_name",
                    "action_name",
                    "status_code",
                    "error_message",
                    "error_data",
                )
            },
        ),
        (
            "Diagnosis",
            {
                "fields": (
                    "category",
                    "severity",
                    "diagnosis_summary",
                    "diagnosis_detail",
                )
            },
        ),
        (
            "Fix Suggestion",
            {
                "fields": ("has_fix", "fix_description", "fix_action"),
            },
        ),
        (
            "Review",
            {
                "fields": ("status", "review_notes", "reviewed_at"),
            },
        ),
        (
            "Occurrence",
            {
                "fields": ("occurrence_count", "first_seen_at", "last_seen_at", "created_at"),
            },
        ),
    )

    def summary_short(self, obj):
        text = obj.diagnosis_summary or ""
        if len(text) > 80:
            return text[:77] + "..."
        return text

    summary_short.short_description = "Summary"

    def category_badge(self, obj):
        colors = {
            "auth_expired": "red",
            "auth_invalid": "red",
            "auth_permissions": "red",
            "rate_limit": "orange",
            "server_error": "purple",
            "timeout": "orange",
            "connection": "orange",
            "not_found_mapping": "#c90",
            "not_found_path": "#c90",
            "validation_missing": "blue",
            "validation_type": "blue",
        }
        color = colors.get(obj.category, "gray")
        return format_html('<span style="color: {};">{}</span>', color, obj.category)

    category_badge.short_description = "Category"

    def severity_badge(self, obj):
        colors = {"low": "green", "medium": "orange", "high": "red", "critical": "darkred"}
        color = colors.get(obj.severity, "gray")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.severity.upper())

    severity_badge.short_description = "Severity"

    def status_badge(self, obj):
        colors = {
            "pending": "orange",
            "approved": "green",
            "dismissed": "gray",
            "applied": "blue",
            "expired": "lightgray",
        }
        color = colors.get(obj.status, "gray")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.status)

    status_badge.short_description = "Status"

    def has_fix_badge(self, obj):
        if obj.has_fix:
            return format_html('<span style="color: green; font-weight: bold;">Yes</span>')
        return format_html('<span style="color: gray;">—</span>')

    has_fix_badge.short_description = "Fix?"

    def has_add_permission(self, request):
        return False

    actions = ["approve_diagnostics", "dismiss_diagnostics"]

    @admin.action(description="Approve selected diagnostics")
    def approve_diagnostics(self, request, queryset):
        updated = queryset.filter(status="pending").update(status="approved", reviewed_at=timezone.now())
        self.message_user(request, f"{updated} diagnostics approved.")

    @admin.action(description="Dismiss selected diagnostics")
    def dismiss_diagnostics(self, request, queryset):
        updated = queryset.filter(status="pending").update(status="dismissed", reviewed_at=timezone.now())
        self.message_user(request, f"{updated} diagnostics dismissed.")
