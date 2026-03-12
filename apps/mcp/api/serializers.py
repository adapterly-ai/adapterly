"""
Serializers for MCP API.
"""

from rest_framework import serializers

from apps.mcp.models import (
    AgentProfile,
    MCPApiKey,
    MCPAuditLog,
    MCPSession,
    Project,
    ProjectIntegration,
)


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for projects (read-only)."""

    class Meta:
        model = Project
        fields = ["id", "name", "slug", "description", "is_active", "created_at"]
        read_only_fields = fields


class MCPApiKeySerializer(serializers.ModelSerializer):
    """Serializer for MCP API keys (read)."""

    account_name = serializers.CharField(source="account.name", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True, allow_null=True)
    profile_name = serializers.CharField(source="profile.name", read_only=True, allow_null=True)
    project_name = serializers.CharField(source="project.name", read_only=True, allow_null=True)

    class Meta:
        model = MCPApiKey
        fields = [
            "id",
            "name",
            "account",
            "account_name",
            "key_prefix",
            "profile",
            "profile_name",
            "project",
            "project_name",
            "mode",
            "allowed_tools",
            "blocked_tools",
            "is_active",
            "last_used_at",
            "created_at",
            "expires_at",
            "created_by",
            "created_by_username",
        ]
        read_only_fields = [
            "key_prefix",
            "last_used_at",
            "created_at",
            "created_by",
        ]


class MCPApiKeyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating MCP API keys."""

    # The full key is returned only once on creation
    api_key = serializers.CharField(read_only=True)

    class Meta:
        model = MCPApiKey
        fields = [
            "id",
            "name",
            "account",
            "project",
            "profile",
            "is_admin",
            "mode",
            "allowed_tools",
            "blocked_tools",
            "expires_at",
            "api_key",  # Returned only on create
        ]
        read_only_fields = ["account"]

    def create(self, validated_data):
        # Generate key
        key, prefix, key_hash = MCPApiKey.generate_key()

        # Create the API key object
        api_key = MCPApiKey.objects.create(
            key_prefix=prefix, key_hash=key_hash, created_by=self.context["request"].user, **validated_data
        )

        # Attach the full key for response (not saved to DB)
        api_key.api_key = key

        return api_key


class MCPSessionSerializer(serializers.ModelSerializer):
    """Serializer for MCP sessions."""

    account_name = serializers.CharField(source="account.name", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True, allow_null=True)

    class Meta:
        model = MCPSession
        fields = [
            "id",
            "session_id",
            "account",
            "account_name",
            "user",
            "username",
            "mode",
            "transport",
            "is_active",
            "created_at",
            "last_activity",
            "tool_calls_count",
        ]
        read_only_fields = [
            "session_id",
            "created_at",
            "last_activity",
            "tool_calls_count",
        ]


class MCPAuditLogSerializer(serializers.ModelSerializer):
    """Serializer for MCP audit logs."""

    account_name = serializers.CharField(source="account.name", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True, allow_null=True)

    class Meta:
        model = MCPAuditLog
        fields = [
            "id",
            "account",
            "account_name",
            "user",
            "username",
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
        read_only_fields = fields  # Audit logs are read-only


class MCPAuditLogSummarySerializer(serializers.Serializer):
    """Serializer for audit log summary statistics."""

    total_calls = serializers.IntegerField()
    successful_calls = serializers.IntegerField()
    failed_calls = serializers.IntegerField()
    avg_duration_ms = serializers.FloatField()
    tool_breakdown = serializers.DictField()
    date_range = serializers.DictField()


class ProjectIntegrationSerializer(serializers.ModelSerializer):
    """Serializer for project integrations."""

    system_alias = serializers.CharField(source="system.alias", read_only=True)
    system_name = serializers.CharField(source="system.display_name", read_only=True)
    project_slug = serializers.CharField(source="project.slug", read_only=True)

    class Meta:
        model = ProjectIntegration
        fields = [
            "id",
            "project",
            "project_slug",
            "system",
            "system_alias",
            "system_name",
            "external_id",
            "is_enabled",
            "custom_config",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class AgentProfileSerializer(serializers.ModelSerializer):
    """Serializer for agent profiles."""

    project_slug = serializers.CharField(source="project.slug", read_only=True)

    class Meta:
        model = AgentProfile
        fields = [
            "id",
            "project",
            "project_slug",
            "name",
            "description",
            "mode",
            "include_tools",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
