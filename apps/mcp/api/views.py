"""
API Views for MCP management.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.mcp.api.serializers import (
    AgentProfileSerializer,
    MCPApiKeyCreateSerializer,
    MCPApiKeySerializer,
    MCPAuditLogSerializer,
    MCPSessionSerializer,
    ProjectIntegrationSerializer,
    ProjectSerializer,
)
from apps.mcp.models import (
    AgentProfile,
    MCPApiKey,
    MCPAuditLog,
    MCPSession,
    Project,
    ProjectIntegration,
)


class AccountScopedMixin:
    """Mixin to scope querysets to the user's active account."""

    def get_account(self):
        """Resolve account: middleware attr → user's active AccountUser."""
        account = getattr(self.request, "account", None)
        if account:
            return account
        au = getattr(self.request, "active_account_user", None)
        if au:
            return au.account
        if self.request.user.is_authenticated:
            from apps.accounts.models import AccountUser

            au = (
                AccountUser.objects.filter(user=self.request.user, is_current_active=True)
                .select_related("account")
                .first()
            )
            if au:
                return au.account
        return None

    def get_queryset(self):
        queryset = super().get_queryset()
        account = self.get_account()
        if account:
            return queryset.filter(account=account)
        return queryset.none()


class ProjectViewSet(AccountScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for listing projects (read-only).

    list: List all projects for the account
    retrieve: Get project details
    """

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["is_active"]
    search_fields = ["name", "slug"]
    ordering = ["name"]


class AgentProfileViewSet(AccountScopedMixin, viewsets.ModelViewSet):
    """
    API endpoint for managing agent profiles.

    list: List all agent profiles for the account
    create: Create a new profile
    retrieve: Get profile details
    update: Update profile settings
    destroy: Delete a profile
    """

    queryset = AgentProfile.objects.select_related("project").all()
    serializer_class = AgentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["mode", "is_active", "project"]
    search_fields = ["name", "description"]
    ordering = ["name"]

    def perform_create(self, serializer):
        serializer.save(account=self.get_account())


class MCPApiKeyViewSet(AccountScopedMixin, viewsets.ModelViewSet):
    """
    API endpoint for managing MCP API keys.

    list: List all API keys for the account
    create: Create a new API key (returns full key only once)
    retrieve: Get API key details
    update: Update API key settings
    destroy: Delete an API key
    """

    queryset = MCPApiKey.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return MCPApiKeyCreateSerializer
        return MCPApiKeySerializer

    def perform_create(self, serializer):
        serializer.save(account=self.get_account())

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        """Regenerate an API key (creates new key, invalidates old)."""
        api_key = self.get_object()

        # Generate new key
        key, prefix, key_hash = MCPApiKey.generate_key()

        # Update the key
        api_key.key_prefix = prefix
        api_key.key_hash = key_hash
        api_key.save()

        return Response({"api_key": key, "message": "API key regenerated. Save this key - it will not be shown again."})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate an API key."""
        api_key = self.get_object()
        api_key.is_active = False
        api_key.save()
        return Response({"status": "deactivated"})

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate an API key."""
        api_key = self.get_object()
        api_key.is_active = True
        api_key.save()
        return Response({"status": "activated"})


class MCPSessionViewSet(AccountScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing MCP sessions.

    Sessions are read-only through the API.
    """

    queryset = MCPSession.objects.all()
    serializer_class = MCPSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["is_active", "mode", "transport"]
    ordering_fields = ["created_at", "last_activity", "tool_calls_count"]
    ordering = ["-last_activity"]

    @action(detail=False, methods=["get"])
    def active(self, request):
        """Get active sessions."""
        queryset = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def terminate(self, request, pk=None):
        """Terminate (deactivate) a session."""
        session = self.get_object()
        session.is_active = False
        session.save()
        return Response({"status": "terminated"})


class MCPAuditLogViewSet(AccountScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing MCP audit logs.

    Audit logs are read-only.
    """

    queryset = MCPAuditLog.objects.all()
    serializer_class = MCPAuditLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["tool_type", "success", "mode", "transport", "tool_name"]
    search_fields = ["tool_name", "session_id", "error_message"]
    ordering_fields = ["timestamp", "duration_ms"]
    ordering = ["-timestamp"]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Get audit log summary statistics."""
        queryset = self.get_queryset()

        # Apply date filter if provided
        days = int(request.query_params.get("days", 7))
        since = timezone.now() - timedelta(days=days)
        queryset = queryset.filter(timestamp__gte=since)

        # Calculate statistics
        stats = queryset.aggregate(
            total_calls=Count("id"),
            successful_calls=Count("id", filter=Q(success=True)),
            failed_calls=Count("id", filter=Q(success=False)),
            avg_duration_ms=Avg("duration_ms"),
        )

        # Tool breakdown
        tool_breakdown = dict(
            queryset.values("tool_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
            .values_list("tool_name", "count")
        )

        # Tool type breakdown
        type_breakdown = dict(
            queryset.values("tool_type").annotate(count=Count("id")).values_list("tool_type", "count")
        )

        return Response(
            {
                "total_calls": stats["total_calls"] or 0,
                "successful_calls": stats["successful_calls"] or 0,
                "failed_calls": stats["failed_calls"] or 0,
                "success_rate": (stats["successful_calls"] / stats["total_calls"] * 100 if stats["total_calls"] else 0),
                "avg_duration_ms": round(stats["avg_duration_ms"] or 0, 2),
                "tool_breakdown": tool_breakdown,
                "type_breakdown": type_breakdown,
                "date_range": {"from": since.isoformat(), "to": timezone.now().isoformat(), "days": days},
            }
        )

    @action(detail=False, methods=["get"])
    def by_session(self, request):
        """Get audit logs grouped by session."""
        session_id = request.query_params.get("session_id")
        if not session_id:
            return Response({"error": "session_id parameter required"}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(session_id=session_id)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def errors(self, request):
        """Get recent error logs."""
        limit = min(int(request.query_params.get("limit", 50)), 500)
        queryset = self.get_queryset().filter(success=False)[:limit]
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ProjectIntegrationViewSet(AccountScopedMixin, viewsets.ModelViewSet):
    """
    API endpoint for managing project integrations.

    Integrations link projects to systems with credential source and external IDs.
    """

    queryset = ProjectIntegration.objects.select_related("project", "system").all()
    serializer_class = ProjectIntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["project", "system", "is_enabled"]
    search_fields = ["system__alias", "system__display_name", "external_id"]
    ordering = ["system__alias"]

    def get_queryset(self):
        queryset = ProjectIntegration.objects.select_related("project", "system")
        account = self.get_account()
        if account:
            return queryset.filter(project__account=account)
        return queryset.none()

    def perform_destroy(self, instance):
        """Remove integration and clean up project-scoped credentials."""
        from apps.systems.models import AccountSystem

        account = instance.project.account
        system_id = instance.system_id
        project = instance.project

        instance.delete()

        AccountSystem.objects.filter(
            account=account,
            system_id=system_id,
            project=project,
        ).delete()

    @action(detail=False, methods=["get"], url_path="by-project/(?P<project_id>[^/.]+)")
    def by_project(self, request, project_id=None):
        """Get integrations for a specific project."""
        queryset = self.get_queryset().filter(project_id=project_id)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
