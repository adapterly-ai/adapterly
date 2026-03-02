"""
Serializers for the Gateway Sync API.
"""

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class GatewayRegisterRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, default="")


class GatewayRegisterResponseSerializer(serializers.Serializer):
    gateway_id = serializers.CharField()
    gateway_secret = serializers.CharField()
    message = serializers.CharField()


# ---------------------------------------------------------------------------
# Spec sync
# ---------------------------------------------------------------------------


class InterfaceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    alias = serializers.CharField()
    name = serializers.CharField()
    type = serializers.CharField()
    base_url = serializers.CharField()
    auth = serializers.JSONField()
    requires_browser = serializers.BooleanField()
    browser = serializers.JSONField()
    rate_limits = serializers.JSONField()
    graphql_schema = serializers.JSONField()


class ResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    interface_id = serializers.IntegerField()
    alias = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()


class ActionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    resource_id = serializers.IntegerField()
    alias = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    method = serializers.CharField()
    path = serializers.CharField()
    headers = serializers.JSONField()
    parameters_schema = serializers.JSONField()
    output_schema = serializers.JSONField()
    pagination = serializers.JSONField()
    errors = serializers.JSONField()
    examples = serializers.JSONField()
    is_mcp_enabled = serializers.BooleanField()


class SystemSpecSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    alias = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField()
    variables = serializers.JSONField()
    meta = serializers.JSONField()
    schema_digest = serializers.CharField()
    system_type = serializers.CharField()
    icon = serializers.CharField()
    website_url = serializers.CharField()
    docs_url = serializers.CharField()
    is_active = serializers.BooleanField()
    interfaces = InterfaceSerializer(many=True)
    resources = ResourceSerializer(many=True)
    actions = ActionSerializer(many=True)


class SpecSyncResponseSerializer(serializers.Serializer):
    systems = SystemSpecSerializer(many=True)
    deleted_ids = serializers.ListField(child=serializers.IntegerField())
    sync_timestamp = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# Key sync
# ---------------------------------------------------------------------------


class ProjectIntegrationSyncSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    project_id = serializers.IntegerField()
    system_id = serializers.IntegerField()
    credential_source = serializers.CharField()
    external_id = serializers.CharField()
    is_enabled = serializers.BooleanField()
    custom_config = serializers.JSONField()


class ProjectSyncSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    description = serializers.CharField()
    external_mappings = serializers.JSONField()
    is_active = serializers.BooleanField()


class MCPApiKeySyncSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    name = serializers.CharField()
    key_prefix = serializers.CharField()
    key_hash = serializers.CharField()
    project_id = serializers.IntegerField(allow_null=True)
    is_admin = serializers.BooleanField()
    mode = serializers.CharField()
    allowed_tools = serializers.JSONField()
    blocked_tools = serializers.JSONField()
    is_active = serializers.BooleanField()
    expires_at = serializers.DateTimeField(allow_null=True)


class KeySyncResponseSerializer(serializers.Serializer):
    keys = MCPApiKeySyncSerializer(many=True)
    projects = ProjectSyncSerializer(many=True)
    integrations = ProjectIntegrationSyncSerializer(many=True)
    sync_timestamp = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# Audit push
# ---------------------------------------------------------------------------


class AuditEntrySerializer(serializers.Serializer):
    tool_name = serializers.CharField(max_length=255)
    tool_type = serializers.CharField(max_length=50)
    duration_ms = serializers.IntegerField(default=0)
    success = serializers.BooleanField(default=True)
    error_message = serializers.CharField(default="", allow_blank=True)
    error_category = serializers.CharField(default="", allow_blank=True)
    session_id = serializers.CharField(default="", allow_blank=True)
    mode = serializers.CharField(default="safe")
    timestamp = serializers.DateTimeField()


class AuditPushRequestSerializer(serializers.Serializer):
    entries = AuditEntrySerializer(many=True)


# ---------------------------------------------------------------------------
# Health push
# ---------------------------------------------------------------------------


class HealthPushSerializer(serializers.Serializer):
    status = serializers.CharField()
    last_spec_sync = serializers.DateTimeField(allow_null=True, required=False)
    last_key_sync = serializers.DateTimeField(allow_null=True, required=False)
    active_sessions = serializers.IntegerField(default=0)
    version = serializers.CharField(default="")
    hostname = serializers.CharField(default="", allow_blank=True)
    credential_status = serializers.JSONField(required=False, default=dict)
