"""
User-facing views for Project management.

Slug-based URL structure: /projects/<slug>/...
"""

import re
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.accounts.utils import get_active_account, get_active_account_user
from apps.mcp.models import (
    AgentProfile,
    ErrorDiagnostic,
    MCPApiKey,
    MCPAuditLog,
    Project,
    ProjectIntegration,
)


def _get_project_for_account(request, slug):
    """Get a project by slug, scoped to the active account."""
    active_account = get_active_account(request)
    if not active_account:
        return None, None
    project = get_object_or_404(Project, slug=slug, account=active_account)
    return active_account, project


# ============================================================================
# Project CRUD
# ============================================================================


@login_required
def project_list(request):
    """List all projects for the active account."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    # Per-project: count of pending errors linked via integration system aliases
    recent_error_subquery = (
        ErrorDiagnostic.objects.filter(
            account=active_account,
            status="pending",
            last_seen_at__gte=timezone.now() - timedelta(days=7),
            system_alias__in=Subquery(
                ProjectIntegration.objects.filter(
                    project=OuterRef(OuterRef("pk")),
                    is_enabled=True,
                ).values("system__alias")
            ),
        )
        .values("account")
        .annotate(cnt=Count("id"))
        .values("cnt")
    )

    projects = (
        Project.objects.filter(account=active_account)
        .annotate(
            integration_count=Count("integrations", distinct=True),
            profile_count=Count("agent_profiles", distinct=True),
            token_count=Count("agent_profiles__api_keys", distinct=True),
            active_integration_count=Count("integrations", filter=Q(integrations__is_enabled=True), distinct=True),
            recent_errors=Coalesce(Subquery(recent_error_subquery[:1], output_field=IntegerField()), Value(0)),
        )
        .order_by("name")
    )

    # Account-level aggregates
    total_integrations = ProjectIntegration.objects.filter(project__account=active_account).count()
    total_profiles = AgentProfile.objects.filter(project__account=active_account).count()
    total_tokens = MCPApiKey.objects.filter(account=active_account).count()
    recent_runs = MCPAuditLog.objects.filter(
        account=active_account,
        timestamp__gte=timezone.now() - timedelta(days=30),
    ).count()

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "projects": projects,
        "total_integrations": total_integrations,
        "total_profiles": total_profiles,
        "total_tokens": total_tokens,
        "recent_runs": recent_runs,
    }

    return render(request, "mcp/project_list.html", context)


@login_required
def project_create(request):
    """Create a new project."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user:
        messages.error(request, "Admin access required")
        return redirect("projects:list")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()

        if not name:
            messages.error(request, "Workspace name is required")
        else:
            slug = slugify(name)[:100]
            if not slug:
                slug = "project"

            # Ensure unique slug within account
            base_slug = slug
            counter = 1
            while Project.objects.filter(account=active_account, slug=slug).exists():
                slug = f"{base_slug}-{counter}"[:100]
                counter += 1

            project = Project.objects.create(
                account=active_account,
                name=name,
                slug=slug,
                description=description,
            )
            messages.success(request, f"Workspace '{name}' created")
            return redirect("projects:detail", slug=project.slug)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
    }

    return render(request, "mcp/project_form.html", context)


@login_required
def project_detail(request, slug):
    """Project workspace dashboard with integration health monitoring."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    integrations = ProjectIntegration.objects.filter(project=project).select_related("system")
    profiles = AgentProfile.objects.filter(project=project).prefetch_related("api_keys")

    # --- Monitoring KPIs (last 7 days) ---
    since_7d = timezone.now() - timedelta(days=7)

    # Get system aliases for this project's integrations
    integration_aliases = list(integrations.filter(is_enabled=True).values_list("system__alias", flat=True))

    # Filter audit logs by tool names that match project integrations
    log_filters = Q(account=active_account, timestamp__gte=since_7d)
    if integration_aliases:
        alias_q = Q()
        for alias in integration_aliases:
            alias_q |= Q(tool_name__startswith=f"{alias}_")
        log_filters &= alias_q

    logs_qs = MCPAuditLog.objects.filter(log_filters)

    from django.db.models import Avg

    stats = logs_qs.aggregate(
        total=Count("id"),
        successful=Count("id", filter=Q(success=True)),
        failed=Count("id", filter=Q(success=False)),
        avg_duration=Avg("duration_ms"),
    )

    total_calls = stats["total"] or 0
    failed_calls = stats["failed"] or 0
    success_rate = round((stats["successful"] or 0) / total_calls * 100, 1) if total_calls > 0 else None
    avg_duration = round(stats["avg_duration"] or 0)

    # Per-integration health
    integration_health = []
    for integration in integrations.filter(is_enabled=True):
        alias = integration.system.alias
        int_logs = MCPAuditLog.objects.filter(
            account=active_account,
            tool_name__startswith=f"{alias}_",
            timestamp__gte=since_7d,
        )
        int_stats = int_logs.aggregate(
            total=Count("id"),
            failed=Count("id", filter=Q(success=False)),
        )
        int_total = int_stats["total"] or 0
        int_failed = int_stats["failed"] or 0
        int_success_rate = round((int_total - int_failed) / int_total * 100, 1) if int_total > 0 else None

        # Determine health status
        if int_total == 0:
            health = "no_data"
        elif int_failed == 0:
            health = "healthy"
        elif int_success_rate and int_success_rate >= 90:
            health = "warning"
        else:
            health = "error"

        integration_health.append(
            {
                "integration": integration,
                "total_calls": int_total,
                "failed_calls": int_failed,
                "success_rate": int_success_rate,
                "health": health,
            }
        )

    # Recent error diagnostics for this project's systems
    recent_diagnostics = []
    if integration_aliases:
        recent_diagnostics = list(
            ErrorDiagnostic.objects.filter(
                account=active_account,
                system_alias__in=integration_aliases,
                status="pending",
            ).order_by("-last_seen_at")[:10]
        )

    # Total log count (all time)
    log_count = MCPAuditLog.objects.filter(account=active_account).count()

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "integrations": integrations,
        "profiles": profiles,
        "integration_count": integrations.count(),
        "profile_count": profiles.count(),
        "log_count": log_count,
        # Monitoring KPIs
        "total_calls_7d": total_calls,
        "failed_calls_7d": failed_calls,
        "success_rate": success_rate,
        "avg_duration": avg_duration,
        "integration_health": integration_health,
        "recent_diagnostics": recent_diagnostics,
        "active_tab": "overview",
    }

    return render(request, "mcp/project_detail.html", context)


@login_required
def project_edit(request, slug):
    """Edit a project."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user:
        messages.error(request, "Admin access required")
        return redirect("projects:detail", slug=slug)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Workspace name is required")
        else:
            project.name = name
            project.description = description
            project.is_active = is_active
            project.save()
            messages.success(request, f"Workspace '{name}' updated")
            return redirect("projects:detail", slug=project.slug)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
    }

    return render(request, "mcp/project_form.html", context)


@login_required
@require_POST
def project_delete(request, slug):
    """Delete a project."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user:
        messages.error(request, "Admin access required")
        return redirect("projects:detail", slug=slug)

    project_name = project.name
    project.delete()
    messages.success(request, f"Workspace '{project_name}' deleted")
    return redirect("projects:list")


# ============================================================================
# Project-scoped Integrations (slug-based wrappers)
# ============================================================================


def _sanitize_tool_name(name):
    """Sanitize tool name to be MCP-compliant."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    name = name.lower()
    return name


def _get_integration_tools(integration):
    """Load tools for an integration from Action models.

    Returns a list of dicts with name, description, tool_type, is_enabled.
    """
    from apps.systems.models import Action

    system = integration.system
    allowed = integration.allowed_actions  # None = all, list = specific

    actions = Action.objects.filter(
        resource__interface__system=system,
        is_mcp_enabled=True,
        resource__interface__system__is_active=True,
    ).select_related("resource__interface__system")

    tools = []
    for action in actions:
        resource = action.resource
        interface = resource.interface
        prefix = system.mcp_prefix or system.alias
        tool_name = f"{prefix}_{resource.alias or resource.name}_{action.alias or action.name}"
        tool_name = _sanitize_tool_name(tool_name)

        method = action.method.upper()
        interface_type = interface.type.upper()
        if interface_type == "GRAPHQL":
            action_name_lower = (action.alias or action.name).lower()
            if any(
                prefix in action_name_lower
                for prefix in ["create", "update", "delete", "add", "remove", "set", "mutate"]
            ):
                tool_type = "system_write"
            else:
                tool_type = "system_read"
        elif method in ("GET", "HEAD", "OPTIONS"):
            tool_type = "system_read"
        else:
            tool_type = "system_write"

        description = action.description or f"{action.name} on {system.display_name} {resource.name}"
        is_enabled = allowed is None or tool_name in allowed
        tools.append(
            {
                "name": tool_name,
                "description_short": description[:200],
                "description": description,
                "tool_type": tool_type,
                "is_enabled": is_enabled,
                "method": method,
                "path": action.path or "",
                "parameters_schema": action.parameters_schema or {},
                "output_schema": action.output_schema or {},
                "examples": action.examples or [],
                "pagination": action.pagination or {},
                "interface_type": interface_type,
            }
        )
    return tools


@login_required
def project_integrations_view(request, slug):
    """List integrations for a project with inline tool selection."""
    from apps.systems.models import AccountSystem

    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    integrations = ProjectIntegration.objects.filter(project=project).select_related("system")

    # Handle POST: save tool selections
    if request.method == "POST" and active_account_user:
        for integration in integrations:
            system_alias = integration.system.alias
            select_mode = request.POST.get(f"mode_{system_alias}", "all")
            if select_mode == "all":
                integration.allowed_actions = None
            else:
                selected = request.POST.getlist(f"tools_{system_alias}")
                integration.allowed_actions = selected if selected else []
            integration.save(update_fields=["allowed_actions"])
        messages.success(request, "Tool selection saved")
        return redirect("projects:integrations", slug=slug)

    # Build credential status per integration (always workspace-level)
    project_accsys = {
        as_obj.system_id: as_obj
        for as_obj in AccountSystem.objects.filter(
            account=active_account, project=project
        ).select_related("system")
    }

    integration_credentials = {}
    for integration in integrations:
        accsys = project_accsys.get(integration.system_id)

        if accsys is None:
            cred_status = "none"
            cred_label = "No credentials"
            cred_color = "secondary"
        elif accsys.is_verified:
            cred_status = "verified"
            cred_label = "Verified"
            cred_color = "success"
        elif accsys.last_error:
            cred_status = "error"
            cred_label = "Error"
            cred_color = "danger"
        else:
            cred_status = "unverified"
            cred_label = "Not verified"
            cred_color = "warning"

        integration_credentials[integration.id] = {
            "status": cred_status,
            "label": cred_label,
            "color": cred_color,
            "last_error": (accsys.last_error[:120] + "...") if accsys and accsys.last_error and len(accsys.last_error) > 120 else (accsys.last_error if accsys else None),
            "last_verified_at": accsys.last_verified_at if accsys else None,
        }

    # Build tool groups per integration
    tool_groups = []
    for integration in integrations:
        # Attach credential status to integration for template access
        cred_info = integration_credentials.get(integration.id, {})
        integration.cred_status = cred_info.get("status", "none")
        integration.cred_label = cred_info.get("label", "No credentials")
        integration.cred_color = cred_info.get("color", "secondary")
        integration.cred_last_error = cred_info.get("last_error")
        integration.cred_last_verified_at = cred_info.get("last_verified_at")

        tools = _get_integration_tools(integration)
        enabled_count = sum(1 for t in tools if t["is_enabled"])
        tool_groups.append(
            {
                "integration": integration,
                "system": integration.system.display_name,
                "system_alias": integration.system.alias,
                "tools": tools,
                "select_mode": "all" if integration.allowed_actions is None else "custom",
                "enabled_count": enabled_count,
            }
        )

    total_tools = sum(len(g["tools"]) for g in tool_groups)
    enabled_tools = sum(g["enabled_count"] for g in tool_groups)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "integrations": integrations,
        "integration_credentials": integration_credentials,
        "tool_groups": tool_groups,
        "total_tools": total_tools,
        "enabled_tools": enabled_tools,
        "active_tab": "integrations",
    }

    return render(request, "mcp/project_integrations.html", context)


@login_required
def project_integration_add_view(request, slug):
    """Add a system integration to a project (slug-based)."""
    from apps.systems.models import AccountSystem, System

    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "Admin access required")
        return redirect("projects:list")

    available_systems = System.objects.filter(
        is_active=True,
    ).distinct()

    # Mark already-integrated systems and annotate tool counts
    already_integrated_ids = set(
        ProjectIntegration.objects.filter(project=project).values_list("system_id", flat=True)
    )
    from apps.systems.models import Action

    for system in available_systems:
        system.already_integrated = system.id in already_integrated_ids
        system.tool_count = Action.objects.filter(
            resource__interface__system=system,
            is_mcp_enabled=True,
        ).count()
        system.type_label = dict(System.SYSTEM_TYPES).get(system.system_type, system.system_type)

    if request.method == "POST":
        system_id = request.POST.get("system_id")
        notes = request.POST.get("notes", "").strip()

        if not system_id:
            messages.error(request, "System is required")
        else:
            try:
                system = System.objects.get(id=system_id, is_active=True)
            except System.DoesNotExist:
                messages.error(request, "System not found")
                return redirect("projects:integrations", slug=slug)

            integration = ProjectIntegration.objects.create(
                project=project,
                system=system,
                notes=notes,
                is_enabled=True,
            )
            messages.success(request, f"Integration with {system.display_name} added")

            # Always redirect to credentials page to configure workspace credentials
            return redirect("projects:integration_credentials", slug=slug, integration_id=integration.id)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "available_systems": available_systems,
        "active_tab": "integrations",
    }

    return render(request, "mcp/project_integration_form.html", context)


@login_required
def project_integration_edit_view(request, slug, integration_id):
    """Edit a project integration (slug-based)."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "Admin access required")
        return redirect("projects:list")

    integration = get_object_or_404(ProjectIntegration, id=integration_id, project=project)

    if request.method == "POST":
        is_enabled = request.POST.get("is_enabled") == "on"
        notes = request.POST.get("notes", "").strip()
        external_id = request.POST.get("external_id", "").strip()

        integration.is_enabled = is_enabled
        integration.notes = notes
        integration.external_id = external_id
        integration.save()

        messages.success(request, f"Integration with {integration.system.display_name} updated")
        return redirect("projects:integrations", slug=slug)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "integration": integration,
        "active_tab": "integrations",
    }

    return render(request, "mcp/project_integration_form.html", context)


@login_required
@require_POST
def project_integration_remove_view(request, slug, integration_id):
    """Remove a project integration (slug-based)."""
    active_account, project = _get_project_for_account(request, slug)

    if not active_account:
        return JsonResponse({"error": "Admin access required"}, status=403)

    integration = get_object_or_404(ProjectIntegration, id=integration_id, project=project)

    system_name = integration.system.display_name
    system_id = integration.system_id

    # Collect tool names for this integration before deleting
    removed_tools = set()
    try:
        tools = _get_integration_tools(integration)
        removed_tools = {t["name"] for t in tools}
    except Exception:
        pass

    integration.delete()

    # Also clean up project-scoped AccountSystem credentials for this system
    from apps.systems.models import AccountSystem

    AccountSystem.objects.filter(
        account=active_account,
        system_id=system_id,
        project=project,
    ).delete()

    # Clean up stale tool names from agent profiles
    if removed_tools:
        profiles = AgentProfile.objects.filter(project=project)
        for profile in profiles:
            if profile.include_tools:
                cleaned = [t for t in profile.include_tools if t not in removed_tools]
                if len(cleaned) != len(profile.include_tools):
                    profile.include_tools = cleaned
                    profile.save(update_fields=["include_tools"])

    return JsonResponse({"success": True, "message": f"Integration with {system_name} removed"})


@login_required
def project_integration_credentials_view(request, slug, integration_id):
    """Configure project-scoped credentials for an integration."""
    from apps.systems.models import AccountSystem
    from apps.systems.views import _get_auth_fields_for_system

    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("projects:list")

    integration = get_object_or_404(ProjectIntegration, id=integration_id, project=project)
    system = integration.system

    # Get or create project-scoped AccountSystem
    account_system, created = AccountSystem.objects.get_or_create(
        account=active_account,
        system=system,
        project=project,
        defaults={"is_enabled": True},
    )

    if request.method == "POST":
        # Save credential fields
        credential_fields = ["username", "password", "api_key", "token", "client_id", "client_secret", "session_cookie"]
        for field in credential_fields:
            value = request.POST.get(field, "").strip()
            if value:
                setattr(account_system, field, value)

        account_system.is_enabled = request.POST.get("is_enabled") == "on"
        account_system.save()

        messages.success(request, f"Credentials for {system.display_name} saved")
        return redirect("projects:integrations", slug=slug)

    auth_fields = _get_auth_fields_for_system(system)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "integration": integration,
        "system": system,
        "account_system": account_system,
        "auth_fields": auth_fields,
        "active_tab": "integrations",
    }

    return render(request, "mcp/project_integration_credentials.html", context)


@login_required
@require_POST
def project_integration_test_view(request, slug, integration_id):
    """Test connection for a project integration's credentials."""
    from apps.systems.models import AccountSystem
    from apps.systems.services import test_system_connection

    active_account, project = _get_project_for_account(request, slug)
    if not active_account:
        return JsonResponse({"error": "No active account"}, status=403)

    integration = get_object_or_404(ProjectIntegration, id=integration_id, project=project)

    # Find workspace-level AccountSystem credentials
    accsys_filter = {"account": active_account, "system": integration.system, "project": project}

    try:
        account_system = AccountSystem.objects.select_related("system").get(**accsys_filter)
    except AccountSystem.DoesNotExist:
        return JsonResponse({"success": False, "message": "No credentials configured yet."})

    success, message = test_system_connection(account_system)

    if success:
        account_system.mark_verified()
    else:
        account_system.mark_error(message)

    return JsonResponse({"success": success, "message": message})


# ============================================================================
# Project-scoped Tools (redirect to integrations)
# ============================================================================


@login_required
def project_tools_view(request, slug):
    """Tools page with preview modal."""
    import json as _json
    from apps.systems.models import AccountSystem

    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    integrations = ProjectIntegration.objects.filter(project=project).select_related("system")

    tool_groups = []
    total_tools = 0
    enabled_tools = 0

    for integration in integrations:
        tools = _get_integration_tools(integration)
        if not tools:
            continue

        enabled_count = sum(1 for t in tools if t["is_enabled"])
        select_mode = "all" if integration.allowed_actions is None else "custom"

        # Add detail_json for modal preview
        for tool in tools:
            if "detail_json" not in tool:
                tool["detail_json"] = _json.dumps({
                    "name": tool["name"],
                    "description": tool["description"],
                    "method": tool.get("method", ""),
                    "path": tool.get("path", ""),
                    "parameters_schema": tool.get("parameters_schema", {}),
                    "output_schema": tool.get("output_schema", {}),
                    "examples": tool.get("examples", []),
                    "pagination": tool.get("pagination", {}),
                    "interface_type": tool.get("interface_type", ""),
                    "tool_type": tool["tool_type"],
                }).replace("</", r"<\/")

        tool_groups.append({
            "system": integration.system.display_name,
            "system_alias": integration.system.alias,
            "tools": tools,
            "enabled_count": enabled_count,
            "select_mode": select_mode,
        })
        total_tools += len(tools)
        enabled_tools += enabled_count

    # Handle POST: save tool selections
    if request.method == "POST" and active_account_user:
        for integration in integrations:
            system_alias = integration.system.alias
            select_mode = request.POST.get(f"mode_{system_alias}", "all")
            if select_mode == "all":
                integration.allowed_actions = None
            else:
                selected = request.POST.getlist(f"tools_{system_alias}")
                integration.allowed_actions = selected if selected else []
            integration.save(update_fields=["allowed_actions"])
        messages.success(request, "Tool selections saved.")
        return redirect("projects:tools", slug=slug)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "tool_groups": tool_groups,
        "total_tools": total_tools,
        "enabled_tools": enabled_tools,
        "active_tab": "tools",
    }
    return render(request, "mcp/project_tools.html", context)


# ============================================================================
# Project-scoped API Keys
# ============================================================================


@login_required
def project_api_keys_view(request, slug):
    """API keys for a specific project."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    api_keys = MCPApiKey.objects.filter(project=project).select_related("created_by")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "api_keys": api_keys,
        "active_tab": "api_keys",
    }

    return render(request, "mcp/project_api_keys.html", context)


# ============================================================================
# Project-scoped Logs
# ============================================================================


@login_required
def project_logs_view(request, slug):
    """Audit logs for a specific project's API keys."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    # Filter logs by account (MCPAuditLog doesn't have a direct project FK)
    logs = MCPAuditLog.objects.filter(account=active_account).order_by("-timestamp")

    # Apply filters
    tool_name = request.GET.get("tool_name", "")
    success = request.GET.get("success", "")

    if tool_name:
        logs = logs.filter(tool_name__icontains=tool_name)
    if success == "true":
        logs = logs.filter(success=True)
    elif success == "false":
        logs = logs.filter(success=False)

    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "page_obj": page_obj,
        "filter_tool_name": tool_name,
        "filter_success": success,
        "active_tab": "logs",
    }

    return render(request, "mcp/project_logs.html", context)


# ============================================================================
# Project-scoped Agent Profiles
# ============================================================================


def _get_project_tool_groups(project):
    """Load all tools from project integrations, grouped by system.

    Returns list of dicts: {system, system_name, system_alias, tools: [{name, description, tool_type, detail_json, ...}]}
    """
    import json as _json

    integrations = ProjectIntegration.objects.filter(project=project, is_enabled=True).select_related("system")
    groups = []
    for integration in integrations:
        tools = _get_integration_tools(integration)
        if tools:
            for tool in tools:
                tool["detail_json"] = _json.dumps({
                    "name": tool["name"],
                    "description": tool["description"],
                    "method": tool.get("method", ""),
                    "path": tool.get("path", ""),
                    "parameters_schema": tool.get("parameters_schema", {}),
                    "output_schema": tool.get("output_schema", {}),
                    "examples": tool.get("examples", []),
                    "pagination": tool.get("pagination", {}),
                    "interface_type": tool.get("interface_type", ""),
                    "tool_type": tool["tool_type"],
                }).replace("</", r"<\/")
            groups.append(
                {
                    "system": integration.system.display_name,
                    "system_name": integration.system.display_name,
                    "system_alias": integration.system.alias,
                    "tools": tools,
                }
            )
    return groups


@login_required
def project_profiles_view(request, slug):
    """List agent profiles for a project."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    profiles = AgentProfile.objects.filter(project=project).prefetch_related("api_keys").order_by("name")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "profiles": profiles,
        "active_tab": "profiles",
    }

    return render(request, "mcp/project_profiles.html", context)


@login_required
def project_profile_create_view(request, slug):
    """Create an agent profile for a project."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "Admin access required")
        return redirect("projects:list")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        mode = request.POST.get("mode", "safe")

        if not name:
            messages.error(request, "Profile name is required")
        elif AgentProfile.objects.filter(project=project, name=name).exists():
            messages.error(request, f"A profile named '{name}' already exists in this workspace")
        else:
            include_tools = request.POST.getlist("tools")

            profile = AgentProfile.objects.create(
                account=active_account,
                project=project,
                name=name,
                description=description,
                mode=mode,
                include_tools=include_tools,
            )

            messages.success(request, f"Profile '{name}' created")
            return redirect("projects:profile_detail", slug=slug, profile_id=profile.id)

    tool_groups = _get_project_tool_groups(project)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "tool_groups": tool_groups,
        "selected_tools": [],
        "active_tab": "profiles",
    }

    return render(request, "mcp/project_profile_form.html", context)


@login_required
def project_profile_detail_view(request, slug, profile_id):
    """Profile detail with token list."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    profile = get_object_or_404(AgentProfile, id=profile_id, project=project)
    tokens = MCPApiKey.objects.filter(profile=profile).select_related("created_by").order_by("-created_at")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "profile": profile,
        "tokens": tokens,
        "active_tab": "profiles",
    }

    return render(request, "mcp/project_profile_detail.html", context)


@login_required
def project_profile_edit_view(request, slug, profile_id):
    """Edit an agent profile."""
    active_account, project = _get_project_for_account(request, slug)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "Admin access required")
        return redirect("projects:list")

    profile = get_object_or_404(AgentProfile, id=profile_id, project=project)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        mode = request.POST.get("mode", "safe")
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Profile name is required")
        elif AgentProfile.objects.filter(project=project, name=name).exclude(id=profile.id).exists():
            messages.error(request, f"A profile named '{name}' already exists in this workspace")
        else:
            profile.name = name
            profile.description = description
            profile.mode = mode
            profile.is_active = is_active
            profile.include_tools = request.POST.getlist("tools")
            profile.save()

            messages.success(request, f"Profile '{name}' updated")
            return redirect("projects:profile_detail", slug=slug, profile_id=profile.id)

    tool_groups = _get_project_tool_groups(project)

    # Build set of currently valid tool names from active integrations
    valid_tools = set()
    for group in tool_groups:
        for tool in group["tools"]:
            valid_tools.add(tool["name"])

    # Filter include_tools to only valid (active integration) tools
    raw_selected = profile.include_tools or []
    selected_tools = [t for t in raw_selected if t in valid_tools]

    # Auto-clean stale tools from profile if any were removed
    if len(selected_tools) != len(raw_selected):
        profile.include_tools = selected_tools
        profile.save(update_fields=["include_tools"])

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "profile": profile,
        "tool_groups": tool_groups,
        "selected_tools": selected_tools,
        "active_tab": "profiles",
    }

    return render(request, "mcp/project_profile_form.html", context)


@login_required
@require_POST
def project_profile_delete_view(request, slug, profile_id):
    """Delete an agent profile (and its tokens via CASCADE)."""
    active_account, project = _get_project_for_account(request, slug)

    if not active_account:
        return JsonResponse({"error": "Admin access required"}, status=403)

    profile = get_object_or_404(AgentProfile, id=profile_id, project=project)
    profile_name = profile.name
    profile.delete()

    return JsonResponse({"success": True, "message": f"Profile '{profile_name}' deleted"})


# ============================================================================
# MCP Tokens (under profiles)
# ============================================================================


@login_required
@require_POST
def project_profile_token_create_view(request, slug, profile_id):
    """Create a new MCP token under a profile."""
    active_account, project = _get_project_for_account(request, slug)

    if not active_account:
        return JsonResponse({"error": "Admin access required"}, status=403)

    profile = get_object_or_404(AgentProfile, id=profile_id, project=project)

    import json

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        body = {}

    token_name = body.get("name", "").strip() or f"Token for {profile.name}"

    key, prefix, key_hash = MCPApiKey.generate_key()

    MCPApiKey.objects.create(
        account=active_account,
        created_by=request.user,
        name=token_name,
        key_prefix=prefix,
        key_hash=key_hash,
        profile=profile,
        project=project,
        mode=profile.mode,
        is_active=True,
    )

    return JsonResponse(
        {
            "success": True,
            "api_key": key,
            "prefix": prefix,
            "name": token_name,
        }
    )


@login_required
@require_POST
def project_profile_token_toggle_view(request, slug, profile_id, token_id):
    """Toggle a token's active status."""
    active_account, project = _get_project_for_account(request, slug)

    if not active_account:
        return JsonResponse({"error": "Admin access required"}, status=403)

    profile = get_object_or_404(AgentProfile, id=profile_id, project=project)
    token = get_object_or_404(MCPApiKey, id=token_id, profile=profile)

    token.is_active = not token.is_active
    token.save(update_fields=["is_active"])

    return JsonResponse(
        {
            "success": True,
            "is_active": token.is_active,
        }
    )


@login_required
@require_POST
def project_profile_token_delete_view(request, slug, profile_id, token_id):
    """Delete a token."""
    active_account, project = _get_project_for_account(request, slug)

    if not active_account:
        return JsonResponse({"error": "Admin access required"}, status=403)

    profile = get_object_or_404(AgentProfile, id=profile_id, project=project)
    token = get_object_or_404(MCPApiKey, id=token_id, profile=profile)

    token_name = token.name
    token.delete()

    return JsonResponse({"success": True, "message": f"Token '{token_name}' deleted"})
