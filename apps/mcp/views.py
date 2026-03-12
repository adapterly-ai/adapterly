"""
User-facing views for MCP management.
"""

import json
import re
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.utils import get_active_account, get_active_account_user
from apps.mcp.models import (
    AgentProfile,
    MCPApiKey,
    MCPAuditLog,
    MCPSession,
    Project,
    ProjectIntegration,
)


def _sanitize_tool_name(name):
    """Sanitize tool name to be MCP-compliant (matches fastapi_app logic)."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    name = name.lower()
    return name


@login_required
def mcp_dashboard(request):
    """MCP management dashboard - redirects to projects."""
    return redirect("projects:list")


@login_required
def mcp_api_keys(request):
    """API keys management page."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    api_keys = MCPApiKey.objects.filter(account=active_account).select_related("created_by", "project")
    projects = Project.objects.filter(account=active_account, is_active=True)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "api_keys": api_keys,
        "projects": projects,
    }

    return render(request, "mcp/api_keys.html", context)


@login_required
@require_POST
def mcp_create_api_key(request):
    """Create a new API key."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"success": False, "error": "No permission"}, status=403)

    name = request.POST.get("name", "").strip()
    mode = request.POST.get("mode", "safe")
    project_id = request.POST.get("project_id", "").strip()
    is_admin = request.POST.get("is_admin") == "true"
    allowed_tools_json = request.POST.get("allowed_tools", "").strip()

    if not name:
        return JsonResponse({"success": False, "error": "Name is required"})

    if mode not in ("safe", "power"):
        mode = "safe"

    # Parse allowed_tools
    allowed_tools = []
    if allowed_tools_json:
        try:
            allowed_tools = json.loads(allowed_tools_json)
            if not isinstance(allowed_tools, list):
                allowed_tools = []
        except json.JSONDecodeError:
            allowed_tools = []

    # Get project if specified
    project = None
    if project_id:
        try:
            project = Project.objects.get(id=project_id, account=active_account, is_active=True)
        except Project.DoesNotExist:
            return JsonResponse({"success": False, "error": "Project not found"})

    # Generate key
    key, prefix, key_hash = MCPApiKey.generate_key()

    api_key = MCPApiKey.objects.create(
        account=active_account,
        created_by=request.user,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        mode=mode,
        project=project,
        is_admin=is_admin,
        allowed_tools=allowed_tools,
    )

    return JsonResponse(
        {
            "success": True,
            "api_key": key,
            "key_id": api_key.id,
            "message": "API key created. Save this key - it will not be shown again!",
        }
    )


@login_required
@require_POST
def mcp_delete_api_key(request):
    """Delete an API key."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"success": False, "error": "No permission"}, status=403)

    key_id = request.POST.get("key_id")

    try:
        api_key = MCPApiKey.objects.get(id=key_id, account=active_account)
        api_key.delete()
        return JsonResponse({"success": True})
    except MCPApiKey.DoesNotExist:
        return JsonResponse({"success": False, "error": "API key not found"})


@login_required
@require_POST
def mcp_update_api_key(request):
    """Update an API key's name, mode, and allowed_tools."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"success": False, "error": "No permission"}, status=403)

    key_id = request.POST.get("key_id")
    name = request.POST.get("name", "").strip()
    mode = request.POST.get("mode", "").strip()
    allowed_tools_json = request.POST.get("allowed_tools", "").strip()

    if not name:
        return JsonResponse({"success": False, "error": "Name is required"})

    try:
        api_key = MCPApiKey.objects.get(id=key_id, account=active_account)
    except MCPApiKey.DoesNotExist:
        return JsonResponse({"success": False, "error": "API key not found"})

    api_key.name = name

    if mode in ("safe", "power"):
        api_key.mode = mode

    if allowed_tools_json:
        try:
            allowed_tools = json.loads(allowed_tools_json)
            if isinstance(allowed_tools, list):
                api_key.allowed_tools = allowed_tools
        except json.JSONDecodeError:
            pass
    else:
        api_key.allowed_tools = []

    api_key.save()

    return JsonResponse({"success": True})


@login_required
@require_POST
def mcp_toggle_api_key(request):
    """Toggle API key active status."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"success": False, "error": "No permission"}, status=403)

    key_id = request.POST.get("key_id")

    try:
        api_key = MCPApiKey.objects.get(id=key_id, account=active_account)
        api_key.is_active = not api_key.is_active
        api_key.save()
        return JsonResponse({"success": True, "is_active": api_key.is_active})
    except MCPApiKey.DoesNotExist:
        return JsonResponse({"success": False, "error": "API key not found"})


@login_required
def project_tools_json(request, project_id):
    """
    AJAX endpoint: return JSON list of project's system tools grouped by system.

    Used by token create/edit forms for tool selection.
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"error": "No permission"}, status=403)

    project = get_object_or_404(Project, id=project_id, account=active_account)

    # Get enabled integrations for this project
    integrations = ProjectIntegration.objects.filter(project=project, is_enabled=True).select_related("system")

    from apps.systems.models import Action

    systems = []
    for integration in integrations:
        system = integration.system

        # Get MCP-enabled actions for this system
        actions = Action.objects.filter(
            resource__interface__system=system, is_mcp_enabled=True, resource__interface__system__is_active=True
        ).select_related("resource__interface__system")

        tools = []
        for action in actions:
            resource = action.resource
            interface = resource.interface

            # Build tool_name same way as _action_to_tool()
            tool_name = f"{system.alias}_{resource.alias or resource.name}_{action.alias or action.name}"
            tool_name = _sanitize_tool_name(tool_name)

            # Determine tool_type
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

            tools.append(
                {
                    "name": tool_name,
                    "description": description[:200],
                    "tool_type": tool_type,
                }
            )

        if tools:
            systems.append(
                {
                    "system": system.display_name,
                    "system_alias": system.alias,
                    "tools": tools,
                }
            )

    return JsonResponse({"systems": systems})


@login_required
def mcp_logs(request):
    """MCP audit logs viewer."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    # Base queryset
    logs = MCPAuditLog.objects.filter(account=active_account).order_by("-timestamp")

    # Filters
    tool_type = request.GET.get("tool_type", "")
    success = request.GET.get("success", "")
    tool_name = request.GET.get("tool_name", "")
    session_id = request.GET.get("session_id", "")
    days = request.GET.get("days", "7")

    # Apply date filter
    try:
        days_int = int(days)
        if days_int > 0:
            since = timezone.now() - timedelta(days=days_int)
            logs = logs.filter(timestamp__gte=since)
    except ValueError:
        days_int = 7

    # Apply filters
    if tool_type:
        logs = logs.filter(tool_type=tool_type)
    if success == "true":
        logs = logs.filter(success=True)
    elif success == "false":
        logs = logs.filter(success=False)
    if tool_name:
        logs = logs.filter(tool_name__icontains=tool_name)
    if session_id:
        logs = logs.filter(session_id__icontains=session_id)

    # Statistics
    stats_qs = MCPAuditLog.objects.filter(account=active_account)
    if days_int > 0:
        stats_qs = stats_qs.filter(timestamp__gte=timezone.now() - timedelta(days=days_int))

    stats = stats_qs.aggregate(
        total=Count("id"),
        successful=Count("id", filter=Q(success=True)),
        failed=Count("id", filter=Q(success=False)),
        avg_duration=Avg("duration_ms"),
    )

    # Tool breakdown
    tool_breakdown = list(stats_qs.values("tool_name").annotate(count=Count("id")).order_by("-count")[:10])

    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "page_obj": page_obj,
        "stats": stats,
        "tool_breakdown": tool_breakdown,
        # Filters
        "filter_tool_type": tool_type,
        "filter_success": success,
        "filter_tool_name": tool_name,
        "filter_session_id": session_id,
        "filter_days": days,
    }

    return render(request, "mcp/logs.html", context)


@login_required
def mcp_log_detail(request, log_id):
    """View single log entry details."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    log = get_object_or_404(MCPAuditLog, id=log_id, account=active_account)

    # Get related logs from same session
    related_logs = []
    if log.session_id:
        related_logs = (
            MCPAuditLog.objects.filter(account=active_account, session_id=log.session_id)
            .exclude(id=log.id)
            .order_by("-timestamp")[:20]
        )

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "log": log,
        "related_logs": related_logs,
    }

    return render(request, "mcp/log_detail.html", context)


@login_required
def mcp_sessions(request):
    """Active MCP sessions viewer."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    # Get sessions
    sessions = MCPSession.objects.filter(account=active_account).order_by("-last_activity")

    # Filter by active
    show_inactive = request.GET.get("show_inactive", "")
    if not show_inactive:
        sessions = sessions.filter(is_active=True)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "sessions": sessions,
        "show_inactive": show_inactive,
    }

    return render(request, "mcp/sessions.html", context)


@login_required
def mcp_tools(request):
    """List all available MCP tools."""
    from apps.mcp.tools import (
        get_audit_tools,
        get_business_tools,
        get_context_tools,
        get_management_tools,
        get_system_tools,
    )

    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    # Collect all tools by category
    tool_groups = []

    # Context tools
    context_tools = get_context_tools()
    if context_tools:
        tool_groups.append(
            {
                "name": "Context",
                "description": "Set execution context (account, workspace)",
                "icon": "bi-gear",
                "color": "secondary",
                "tools": [_tool_to_dict(t) for t in context_tools],
            }
        )

    # Management tools
    management_tools = get_management_tools()
    if management_tools:
        tool_groups.append(
            {
                "name": "Management",
                "description": "Workspace and account management (Power mode)",
                "icon": "bi-building",
                "color": "warning",
                "tools": [_tool_to_dict(t) for t in management_tools],
            }
        )

    # System tools (from integrations)
    try:
        system_tools = get_system_tools(active_account.id)
        if system_tools:
            tool_groups.append(
                {
                    "name": "System Integrations",
                    "description": "Auto-generated from connected systems",
                    "icon": "bi-plug",
                    "color": "info",
                    "tools": [_tool_to_dict(t) for t in system_tools],
                }
            )
    except Exception:
        pass

    # Business tools
    try:
        business_tools = get_business_tools(active_account.id)
        if business_tools:
            tool_groups.append(
                {
                    "name": "Business Tools",
                    "description": "From capability packs",
                    "icon": "bi-briefcase",
                    "color": "success",
                    "tools": [_tool_to_dict(t) for t in business_tools],
                }
            )
    except Exception:
        pass

    # Audit tools
    audit_tools = get_audit_tools()
    if audit_tools:
        tool_groups.append(
            {
                "name": "Audit",
                "description": "Reasoning and rollback tools",
                "icon": "bi-journal-check",
                "color": "dark",
                "tools": [_tool_to_dict(t) for t in audit_tools],
            }
        )

    # Calculate totals
    total_tools = sum(len(g["tools"]) for g in tool_groups)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "tool_groups": tool_groups,
        "total_tools": total_tools,
    }

    return render(request, "mcp/tools.html", context)


def _tool_to_dict(tool):
    """Convert MCPTool to dictionary for template."""
    import json

    return {
        "name": tool.name,
        "description": tool.description,
        "tool_type": tool.tool_type,
        "input_schema": tool.input_schema,
        "input_schema_json": json.dumps(tool.input_schema),
    }


# ============================================================================
# Agent Profile Management (kept for backward compatibility)
# ============================================================================


@login_required
def agent_profiles(request):
    """List all agent profiles."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    profiles = AgentProfile.objects.filter(account=active_account).prefetch_related("api_keys")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "profiles": profiles,
    }

    return render(request, "mcp/profiles.html", context)


@login_required
def agent_profile_create(request):
    """Create a new agent profile."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("mcp:profiles")

    available_tools = _get_available_tools(active_account)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        mode = request.POST.get("mode", "safe")
        include_tools = request.POST.getlist("include_tools")

        if not name:
            messages.error(request, "Name is required")
        elif AgentProfile.objects.filter(account=active_account, name=name).exists():
            messages.error(request, "A profile with this name already exists")
        else:
            AgentProfile.objects.create(
                account=active_account,
                name=name,
                description=description,
                mode=mode,
                include_tools=include_tools,
            )

            messages.success(request, f"Profile '{name}' created successfully")
            return redirect("mcp:profiles")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "available_tools": available_tools,
    }

    return render(request, "mcp/profile_form.html", context)


@login_required
def agent_profile_edit(request, profile_id):
    """Edit an existing agent profile."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("mcp:profiles")

    profile = get_object_or_404(AgentProfile, id=profile_id, account=active_account)
    available_tools = _get_available_tools(active_account)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        mode = request.POST.get("mode", "safe")
        include_tools = request.POST.getlist("include_tools")
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Name is required")
        elif AgentProfile.objects.filter(account=active_account, name=name).exclude(id=profile_id).exists():
            messages.error(request, "A profile with this name already exists")
        else:
            profile.name = name
            profile.description = description
            profile.mode = mode
            profile.include_tools = include_tools
            profile.is_active = is_active
            profile.save()

            messages.success(request, f"Profile '{name}' updated successfully")
            return redirect("mcp:profiles")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "profile": profile,
        "available_tools": available_tools,
    }

    return render(request, "mcp/profile_form.html", context)


@login_required
@require_POST
def agent_profile_delete(request, profile_id):
    """Delete an agent profile."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"error": "Admin access required"}, status=403)

    profile = get_object_or_404(AgentProfile, id=profile_id, account=active_account)

    # Check if profile is in use
    api_keys_count = profile.api_keys.count()
    if api_keys_count > 0:
        return JsonResponse({"error": f"Cannot delete profile - it is used by {api_keys_count} API key(s)"}, status=400)

    profile_name = profile.name
    profile.delete()

    return JsonResponse({"success": True, "message": f"Profile '{profile_name}' deleted"})


def _get_available_tools(account):
    """Get list of available tools for the account."""
    from apps.mcp.tools import get_management_tools, get_system_tools

    tools = []

    # Add management tools
    for tool in get_management_tools():
        tools.append(
            {"name": tool.name, "description": tool.description, "type": tool.tool_type, "group": "Management"}
        )

    # Add system tools
    try:
        for tool in get_system_tools(account.id):
            tools.append(
                {"name": tool.name, "description": tool.description, "type": tool.tool_type, "group": "System"}
            )
    except Exception:
        pass

    return tools


@login_required
def api_key_test(request, key_id):
    """Test what tools an API key can access.

    Accepts POST with JSON body to test unsaved form values:
    {
        "mode": "safe" | "power",
        "allowed_tools": ["tool1", "tool2"]
    }
    """
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"error": "No permission"}, status=403)

    api_key = get_object_or_404(MCPApiKey, id=key_id, account=active_account)

    # Determine test parameters
    if request.method == "POST" and request.body:
        try:
            form_data = json.loads(request.body)
            test_mode = form_data.get("mode", api_key.mode)
            test_allowed_tools = form_data.get("allowed_tools", [])
        except json.JSONDecodeError:
            test_mode = api_key.mode
            test_allowed_tools = api_key.allowed_tools or []
    else:
        test_mode = api_key.mode
        test_allowed_tools = api_key.allowed_tools or []

    # Get project tools if project is bound
    all_tools = []
    if api_key.project_id:
        # Get tools from project integrations
        integrations = ProjectIntegration.objects.filter(project_id=api_key.project_id, is_enabled=True).select_related(
            "system"
        )

        from apps.systems.models import Action

        for integration in integrations:
            system = integration.system
            actions = Action.objects.filter(
                resource__interface__system=system, is_mcp_enabled=True, resource__interface__system__is_active=True
            ).select_related("resource__interface__system")

            for action in actions:
                resource = action.resource
                interface = resource.interface
                tool_name = f"{system.alias}_{resource.alias or resource.name}_{action.alias or action.name}"
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

                description = action.description or f"{action.name} on {system.display_name}"
                all_tools.append(("Systems", tool_name, tool_type, description[:100], system.display_name))

    # Check each tool against permissions
    results = {
        "allowed": [],
        "blocked": [],
        "api_key": {
            "name": api_key.name,
            "mode": test_mode,
        },
    }

    for group, tool_name, tool_type, description, system_name in all_tools:
        # Apply permission rules
        allowed = True
        reason = ""

        if api_key.is_admin and tool_type in ("system_read", "system_write"):
            allowed = False
            reason = "Admin tokens cannot access system tools"
        elif tool_type == "system_write" and test_mode == "safe":
            allowed = False
            reason = "Write operations blocked in Safe mode"
        elif test_allowed_tools and tool_name not in test_allowed_tools:
            allowed = False
            reason = f"Tool not in allowed list ({len(test_allowed_tools)} tools selected)"

        tool_info = {
            "name": tool_name,
            "group": group,
            "type": tool_type,
            "description": description,
            "system": system_name,
        }
        if allowed:
            results["allowed"].append(tool_info)
        else:
            tool_info["reason"] = reason
            results["blocked"].append(tool_info)

    results["summary"] = {
        "total": len(all_tools),
        "allowed": len(results["allowed"]),
        "blocked": len(results["blocked"]),
    }

    return JsonResponse(results)


@login_required
def api_key_edit(request, key_id):
    """Edit API key permissions - mode + allowed_tools."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("mcp:api_keys")

    api_key = get_object_or_404(MCPApiKey, id=key_id, account=active_account)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        mode = request.POST.get("mode", "safe")
        allowed_tools_json = request.POST.get("allowed_tools", "").strip()

        if not name:
            messages.error(request, "Name is required")
        else:
            api_key.name = name
            api_key.mode = mode

            # Parse allowed_tools
            if allowed_tools_json:
                try:
                    allowed_tools = json.loads(allowed_tools_json)
                    if isinstance(allowed_tools, list):
                        api_key.allowed_tools = allowed_tools
                    else:
                        api_key.allowed_tools = []
                except json.JSONDecodeError:
                    api_key.allowed_tools = []
            else:
                api_key.allowed_tools = []

            api_key.save()

            messages.success(request, f"API key '{name}' updated")
            return redirect("mcp:api_keys")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "api_key": api_key,
        "allowed_tools_json": json.dumps(api_key.allowed_tools or []),
    }

    return render(request, "mcp/api_key_edit.html", context)


# ============================================================================
# Project Integrations Management
# ============================================================================


@login_required
def project_integrations(request, project_id):
    """List integrations for a project."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account")
        return redirect("index")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("index")

    project = get_object_or_404(Project, id=project_id, account=active_account)
    integrations = ProjectIntegration.objects.filter(project=project).select_related("system")

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "integrations": integrations,
    }

    return render(request, "mcp/project_integrations.html", context)


@login_required
def project_integration_add(request, project_id):
    """Add a system integration to a project."""
    from apps.systems.models import AccountSystem, System

    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("mcp:dashboard")

    project = get_object_or_404(Project, id=project_id, account=active_account)

    # Get systems that are connected to this account but not yet integrated with this project
    existing_system_ids = ProjectIntegration.objects.filter(project=project).values_list("system_id", flat=True)

    available_systems = (
        System.objects.filter(
            account_systems__account=active_account,
            account_systems__is_enabled=True,
            is_active=True,
        )
        .exclude(id__in=existing_system_ids)
        .distinct()
    )

    if request.method == "POST":
        system_id = request.POST.get("system_id")
        external_id = request.POST.get("external_id", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not system_id:
            messages.error(request, "System is required")
        else:
            try:
                system = System.objects.get(id=system_id, is_active=True)
            except System.DoesNotExist:
                messages.error(request, "System not found")
                return redirect("mcp:project_integrations", project_id=project.id)

            ProjectIntegration.objects.create(
                project=project,
                system=system,
                external_id=external_id,
                notes=notes,
                is_enabled=True,
            )
            messages.success(request, f"Integration with {system.display_name} added")
            return redirect("mcp:project_integrations", project_id=project.id)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "available_systems": available_systems,
    }

    return render(request, "mcp/project_integration_form.html", context)


@login_required
def project_integration_edit(request, project_id, integration_id):
    """Edit a project integration."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        messages.error(request, "Admin access required")
        return redirect("mcp:dashboard")

    project = get_object_or_404(Project, id=project_id, account=active_account)
    integration = get_object_or_404(ProjectIntegration, id=integration_id, project=project)

    if request.method == "POST":
        external_id = request.POST.get("external_id", "").strip()
        is_enabled = request.POST.get("is_enabled") == "on"
        notes = request.POST.get("notes", "").strip()

        integration.external_id = external_id
        integration.is_enabled = is_enabled
        integration.notes = notes
        integration.save()

        messages.success(request, f"Integration with {integration.system.display_name} updated")
        return redirect("mcp:project_integrations", project_id=project.id)

    context = {
        "active_account": active_account,
        "active_account_user": active_account_user,
        "project": project,
        "integration": integration,
    }

    return render(request, "mcp/project_integration_form.html", context)


@login_required
@require_POST
def project_integration_remove(request, project_id, integration_id):
    """Remove a project integration."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account or not active_account_user.is_admin:
        return JsonResponse({"error": "Admin access required"}, status=403)

    project = get_object_or_404(Project, id=project_id, account=active_account)
    integration = get_object_or_404(ProjectIntegration, id=integration_id, project=project)

    system_name = integration.system.display_name
    system_id = integration.system_id

    integration.delete()

    # Also clean up project-scoped AccountSystem credentials for this system
    from apps.systems.models import AccountSystem

    AccountSystem.objects.filter(
        account=active_account,
        system_id=system_id,
        project=project,
    ).delete()

    return JsonResponse({"success": True, "message": f"Integration with {system_name} removed"})
