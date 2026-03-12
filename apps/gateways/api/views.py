"""
Gateway Sync API views.

Endpoints:
- POST /gateway-sync/v1/register — One-time registration
- GET  /gateway-sync/v1/specs     — Pull adapter specs
- GET  /gateway-sync/v1/keys      — Pull API keys, projects, integrations
- POST /gateway-sync/v1/audit     — Push audit log entries
- POST /gateway-sync/v1/health    — Push health status
"""

import logging

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.mcp.models import MCPApiKey, Project, ProjectIntegration
from apps.systems.models import System

from ..models import Gateway, GatewayAuditLog
from .authentication import GatewaySecretAuthentication, RegistrationTokenAuthentication
from .serializers import (
    AuditPushRequestSerializer,
    GatewayRegisterRequestSerializer,
    HealthPushSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: get gateway from request.auth
# ---------------------------------------------------------------------------


def _get_gateway(request) -> Gateway:
    """Extract gateway from DRF request (set by authentication class)."""
    gateway = request.auth
    if not isinstance(gateway, Gateway):
        raise ValueError("Not authenticated as a gateway")
    return gateway


# ---------------------------------------------------------------------------
# POST /gateway-sync/v1/register
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([RegistrationTokenAuthentication])
@permission_classes([AllowAny])
def register(request):
    """
    Register a gateway using a one-time registration token.

    The token is generated in the admin UI and given to the gateway operator.
    After registration, the token is cleared and a gateway secret is returned.
    """
    try:
        gateway = _get_gateway(request)
    except (ValueError, AttributeError):
        return Response(
            {"error": "Invalid or expired registration token"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    serializer = GatewayRegisterRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Generate credentials
    secret, prefix, secret_hash = Gateway.generate_secret()

    # Update gateway
    if serializer.validated_data.get("name"):
        gateway.name = serializer.validated_data["name"]
    gateway.secret_hash = secret_hash
    gateway.secret_prefix = prefix
    gateway.registration_token = None  # One-time — clear after use
    gateway.status = "active"
    gateway.last_seen_at = timezone.now()
    gateway.save()

    logger.info(f"Gateway registered: {gateway.gateway_id} ({gateway.name})")

    return Response(
        {
            "gateway_id": gateway.gateway_id,
            "gateway_secret": secret,
            "message": "Gateway registered successfully. Store the secret securely — it cannot be retrieved again.",
        },
        status=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# GET /gateway-sync/v1/specs?since={timestamp}
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([GatewaySecretAuthentication])
@permission_classes([AllowAny])
def sync_specs(request):
    """
    Pull adapter specs (System → Interface → Resource → Action).

    Query params:
    - since: ISO timestamp — only return specs updated after this time
    """
    try:
        gateway = _get_gateway(request)
    except ValueError:
        return Response({"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)

    account = gateway.account  # noqa: F841
    since_str = request.query_params.get("since")
    since = parse_datetime(since_str) if since_str else None

    # Get all active systems (control plane has all specs)
    systems_qs = System.objects.filter(is_active=True)
    if since:
        systems_qs = systems_qs.filter(updated_at__gte=since)

    systems_data = []
    for system in systems_qs.prefetch_related("interfaces__resources__actions"):
        interfaces_data = []
        resources_data = []
        actions_data = []

        for interface in system.interfaces.all():
            interfaces_data.append(
                {
                    "id": interface.id,
                    "alias": interface.alias,
                    "name": interface.name,
                    "type": interface.type,
                    "base_url": interface.base_url,
                    "auth": interface.auth,
                    "requires_browser": interface.requires_browser,
                    "browser": interface.browser,
                    "rate_limits": interface.rate_limits,
                    "graphql_schema": interface.graphql_schema,
                }
            )
            for resource in interface.resources.all():
                resources_data.append(
                    {
                        "id": resource.id,
                        "interface_id": interface.id,
                        "alias": resource.alias,
                        "name": resource.name,
                        "description": resource.description,
                    }
                )
                for action in resource.actions.all():
                    actions_data.append(
                        {
                            "id": action.id,
                            "resource_id": resource.id,
                            "alias": action.alias,
                            "name": action.name,
                            "description": action.description,
                            "method": action.method,
                            "path": action.path,
                            "headers": action.headers,
                            "parameters_schema": action.parameters_schema,
                            "output_schema": action.output_schema,
                            "pagination": action.pagination,
                            "errors": action.errors,
                            "examples": action.examples,
                            "is_mcp_enabled": action.is_mcp_enabled,
                        }
                    )

        systems_data.append(
            {
                "id": system.id,
                "name": system.name,
                "alias": system.alias,
                "mcp_prefix": system.mcp_prefix,
                "display_name": system.display_name,
                "description": system.description,
                "variables": system.variables,
                "meta": system.meta,
                "schema_digest": system.schema_digest,
                "system_type": system.system_type,
                "icon": system.icon,
                "website_url": system.website_url,
                "docs_url": system.docs_url,
                "is_active": system.is_active,
                "interfaces": interfaces_data,
                "resources": resources_data,
                "actions": actions_data,
            }
        )

    # Get deleted system IDs (inactive systems that were previously active)
    deleted_ids = []
    if since:
        deleted_ids = list(System.objects.filter(is_active=False, updated_at__gte=since).values_list("id", flat=True))

    # Update gateway sync timestamp
    gateway.last_spec_sync_at = timezone.now()
    gateway.last_seen_at = timezone.now()
    gateway.save(update_fields=["last_spec_sync_at", "last_seen_at"])

    return Response(
        {
            "systems": systems_data,
            "deleted_ids": deleted_ids,
            "sync_timestamp": timezone.now().isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# GET /gateway-sync/v1/keys?since={timestamp}
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([GatewaySecretAuthentication])
@permission_classes([AllowAny])
def sync_keys(request):
    """
    Pull API keys, projects, and integrations for the gateway's account.

    Query params:
    - since: ISO timestamp — only return items updated after this time

    Note: Credentials (AccountSystem) are NEVER synced. They stay on the gateway.
    """
    try:
        gateway = _get_gateway(request)
    except ValueError:
        return Response({"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)

    account = gateway.account
    since_str = request.query_params.get("since")
    since = parse_datetime(since_str) if since_str else None

    # API Keys
    keys_qs = MCPApiKey.objects.filter(account=account, is_active=True)
    if since:
        keys_qs = keys_qs.filter(Q(created_at__gte=since) | Q(last_used_at__gte=since))

    keys_data = []
    for key in keys_qs:
        keys_data.append(
            {
                "id": key.id,
                "account_id": key.account_id,
                "name": key.name,
                "key_prefix": key.key_prefix,
                "key_hash": key.key_hash,
                "project_id": key.project_id,
                "is_admin": key.is_admin,
                "mode": key.mode,
                "allowed_tools": key.allowed_tools,
                "blocked_tools": key.blocked_tools,
                "is_active": key.is_active,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            }
        )

    # Projects
    projects_qs = Project.objects.filter(account=account, is_active=True)
    if since:
        projects_qs = projects_qs.filter(updated_at__gte=since)

    projects_data = []
    for project in projects_qs:
        projects_data.append(
            {
                "id": project.id,
                "account_id": project.account_id,
                "name": project.name,
                "slug": project.slug,
                "description": project.description,
                "external_mappings": project.external_mappings,
                "is_active": project.is_active,
            }
        )

    # Project Integrations
    integrations_qs = ProjectIntegration.objects.filter(
        project__account=account,
        is_enabled=True,
    )
    if since:
        integrations_qs = integrations_qs.filter(updated_at__gte=since)

    integrations_data = []
    for integration in integrations_qs:
        integrations_data.append(
            {
                "id": integration.id,
                "project_id": integration.project_id,
                "system_id": integration.system_id,
                "external_id": integration.external_id,
                "is_enabled": integration.is_enabled,
                "custom_config": integration.custom_config,
            }
        )

    # Update gateway sync timestamp
    gateway.last_key_sync_at = timezone.now()
    gateway.last_seen_at = timezone.now()
    gateway.save(update_fields=["last_key_sync_at", "last_seen_at"])

    return Response(
        {
            "keys": keys_data,
            "projects": projects_data,
            "integrations": integrations_data,
            "sync_timestamp": timezone.now().isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# POST /gateway-sync/v1/audit
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([GatewaySecretAuthentication])
@permission_classes([AllowAny])
def push_audit(request):
    """
    Receive audit log entries from a gateway.

    Body: { "entries": [{ tool_name, duration_ms, success, ... }] }
    """
    try:
        gateway = _get_gateway(request)
    except ValueError:
        return Response({"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)

    serializer = AuditPushRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    entries = serializer.validated_data["entries"]
    created = []

    for entry in entries:
        log = GatewayAuditLog(
            gateway=gateway,
            account=gateway.account,
            tool_name=entry["tool_name"],
            tool_type=entry["tool_type"],
            duration_ms=entry.get("duration_ms", 0),
            success=entry.get("success", True),
            error_message=entry.get("error_message", ""),
            error_category=entry.get("error_category", ""),
            session_id=entry.get("session_id", ""),
            mode=entry.get("mode", "safe"),
            gateway_timestamp=entry["timestamp"],
        )
        created.append(log)

    GatewayAuditLog.objects.bulk_create(created)

    # Update gateway timestamp
    gateway.last_audit_push_at = timezone.now()
    gateway.last_seen_at = timezone.now()
    gateway.save(update_fields=["last_audit_push_at", "last_seen_at"])

    logger.info(f"Received {len(created)} audit entries from gateway {gateway.gateway_id}")

    return Response(
        {
            "received": len(created),
            "message": "Audit entries received",
        }
    )


# ---------------------------------------------------------------------------
# POST /gateway-sync/v1/health
# ---------------------------------------------------------------------------


@api_view(["POST"])
@authentication_classes([GatewaySecretAuthentication])
@permission_classes([AllowAny])
def push_health(request):
    """
    Receive health status from a gateway.

    Body: { status, last_spec_sync, active_sessions, version, credential_status }
    """
    try:
        gateway = _get_gateway(request)
    except ValueError:
        return Response({"error": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)

    serializer = HealthPushSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    gateway.last_seen_at = timezone.now()
    gateway.active_sessions = data.get("active_sessions", 0)
    gateway.version = data.get("version", "")
    gateway.hostname = data.get("hostname", "")

    if data.get("credential_status"):
        gateway.credential_status = data["credential_status"]

    # Update status based on reported health
    reported_status = data.get("status", "healthy")
    if reported_status == "healthy" and gateway.status == "active":
        pass  # Keep active
    elif reported_status == "degraded":
        logger.warning(f"Gateway {gateway.gateway_id} reports degraded status")

    gateway.save()

    return Response({"status": "ok"})
