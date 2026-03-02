"""
Gateway admin — register and manage gateways from the control plane.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Gateway, GatewayAuditLog


@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    list_display = [
        "name", "gateway_id", "account", "status",
        "last_seen_display", "version", "active_sessions",
    ]
    list_filter = ["status", "account"]
    search_fields = ["name", "gateway_id"]
    readonly_fields = [
        "gateway_id", "secret_prefix", "secret_hash",
        "last_seen_at", "last_spec_sync_at", "last_key_sync_at",
        "last_audit_push_at", "credential_status",
        "created_at", "updated_at", "registration_token_display",
    ]
    fieldsets = [
        (None, {
            "fields": ("account", "name", "description", "status"),
        }),
        ("Identity", {
            "fields": ("gateway_id", "secret_prefix"),
        }),
        ("Registration", {
            "fields": ("registration_token_display",),
            "description": "Use 'Create Registration Token' action to generate a one-time token.",
        }),
        ("Health", {
            "fields": (
                "last_seen_at", "last_spec_sync_at", "last_key_sync_at",
                "last_audit_push_at", "version", "active_sessions", "hostname",
            ),
        }),
        ("Credential Status", {
            "fields": ("credential_status",),
            "description": "Shows which systems have credentials configured on this gateway (no values).",
        }),
    ]
    actions = ["create_registration_token", "revoke_gateway"]

    def last_seen_display(self, obj):
        if not obj.last_seen_at:
            return "Never"
        from django.utils.timesince import timesince
        return f"{timesince(obj.last_seen_at)} ago"
    last_seen_display.short_description = "Last Seen"

    def registration_token_display(self, obj):
        if obj.registration_token:
            return format_html(
                '<code style="background:#f0f0f0;padding:4px 8px">{}</code>'
                '<br><small>Give this to the gateway operator. It can only be used once.</small>',
                obj.registration_token,
            )
        return "No active token. Use the action to create one."
    registration_token_display.short_description = "Registration Token"

    @admin.action(description="Create registration token for selected gateways")
    def create_registration_token(self, request, queryset):
        for gw in queryset:
            gw.registration_token = Gateway.generate_registration_token()
            if not gw.gateway_id:
                gw.gateway_id = Gateway.generate_gateway_id()
            gw.status = "pending"
            gw.save()
        self.message_user(request, f"Created registration tokens for {queryset.count()} gateway(s).")

    @admin.action(description="Revoke selected gateways")
    def revoke_gateway(self, request, queryset):
        queryset.update(status="revoked")
        self.message_user(request, f"Revoked {queryset.count()} gateway(s).")


@admin.register(GatewayAuditLog)
class GatewayAuditLogAdmin(admin.ModelAdmin):
    list_display = ["gateway", "tool_name", "success", "duration_ms", "gateway_timestamp"]
    list_filter = ["success", "gateway", "tool_type"]
    search_fields = ["tool_name"]
    readonly_fields = [
        "gateway", "account", "tool_name", "tool_type",
        "duration_ms", "success", "error_message", "error_category",
        "session_id", "mode", "gateway_timestamp", "received_at",
    ]
    date_hierarchy = "gateway_timestamp"
