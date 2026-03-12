"""
Adapter Generator Wizard Views.

Provides a step-by-step wizard for creating system adapters:
1. Source selection
2. Discovery & analysis
3. Review & edit
4. Test & save
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.utils import get_active_account, get_active_account_user

logger = logging.getLogger(__name__)


# Session keys for wizard state
WIZARD_STATE_KEY = "adapter_wizard_state"


def get_wizard_state(request) -> dict:
    """Get current wizard state from session."""
    return request.session.get(
        WIZARD_STATE_KEY,
        {
            "step": 1,
            "source_type": None,
            "system_name": "",
            "system_alias": "",
            "base_url": "",
            "auth_type": "none",
            "auth_config": {},
            "endpoints": [],
            "resources": {},
        },
    )


def save_wizard_state(request, state: dict):
    """Save wizard state to session."""
    request.session[WIZARD_STATE_KEY] = state
    request.session.modified = True


def clear_wizard_state(request):
    """Clear wizard state."""
    if WIZARD_STATE_KEY in request.session:
        del request.session[WIZARD_STATE_KEY]


@login_required
def wizard_start(request):
    """Start the adapter wizard - Step 1: Source selection."""
    active_account = get_active_account(request)
    active_account_user = get_active_account_user(request)

    if not active_account:
        messages.error(request, "No active account.")
        return redirect("account_dashboard")

    if not active_account_user.is_admin:
        messages.error(request, "Admin access required.")
        return redirect("systems_dashboard")

    # Clear previous state on fresh start
    if request.GET.get("fresh"):
        clear_wizard_state(request)

    state = get_wizard_state(request)
    state["step"] = 1

    context = {
        "state": state,
        "step": 1,
        "total_steps": 4,
    }

    return render(request, "systems/wizard/step1_source.html", context)


@login_required
@require_POST
def wizard_step1_submit(request):
    """Process Step 1: Source selection."""
    state = get_wizard_state(request)

    source_type = request.POST.get("source_type")
    system_name = request.POST.get("system_name", "").strip()
    system_alias = request.POST.get("system_alias", "").strip()
    base_url = request.POST.get("base_url", "").strip()

    # Validation
    if not source_type:
        messages.error(request, "Please select a source type.")
        return redirect("wizard_start")

    if source_type in ("documentation", "manual", "browser") and not system_name:
        messages.error(request, "System name is required.")
        return redirect("wizard_start")

    # Update state
    state["source_type"] = source_type
    state["system_name"] = system_name
    state["system_alias"] = system_alias or _slugify(system_name)
    state["base_url"] = base_url
    state["step"] = 2

    # Handle file uploads
    if source_type == "openapi_file" and "openapi_file" in request.FILES:
        file = request.FILES["openapi_file"]
        content = file.read().decode("utf-8")
        state["openapi_content"] = content
        state["openapi_filename"] = file.name

    if source_type == "har" and "har_file" in request.FILES:
        file = request.FILES["har_file"]
        content = file.read().decode("utf-8")
        state["har_content"] = content
        state["har_filename"] = file.name

    # Store URL for URL-based sources
    if source_type == "openapi_url":
        state["openapi_url"] = request.POST.get("openapi_url", "").strip()

    if source_type == "documentation":
        state["docs_url"] = request.POST.get("docs_url", "").strip()

    save_wizard_state(request, state)

    return redirect("wizard_step2")


@login_required
def wizard_step2(request):
    """Step 2: Discovery & Analysis."""
    state = get_wizard_state(request)

    if state["step"] < 2:
        return redirect("wizard_start")

    context = {
        "state": state,
        "step": 2,
        "total_steps": 4,
    }

    return render(request, "systems/wizard/step2_discover.html", context)


@login_required
def wizard_discover_stream(request):
    """
    Stream discovery progress via Server-Sent Events.

    Returns SSE stream with progress updates.
    """
    from apps.systems.adapter_generator import AdapterGenerator

    state = get_wizard_state(request)

    def generate():
        """Generate SSE events."""
        try:
            # Send start event
            yield f"data: {json.dumps({'type': 'start', 'message': 'Starting discovery...'})}\n\n"

            source_type = state.get("source_type")
            generator = AdapterGenerator()

            # Process based on source type
            if source_type == "openapi_url":
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Fetching OpenAPI spec...', 'percent': 10})}\n\n"

                system = generator.from_openapi(spec_url=state.get("openapi_url"))
                state["generated_system"] = generator.to_dict(system)

                yield f"data: {json.dumps({'type': 'progress', 'message': 'Parsing complete', 'percent': 100})}\n\n"

            elif source_type == "openapi_file":
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Parsing OpenAPI file...', 'percent': 20})}\n\n"

                content = state.get("openapi_content", "{}")
                filename = state.get("openapi_filename", "spec.json")

                import yaml

                if filename.endswith((".yaml", ".yml")):
                    spec = yaml.safe_load(content)
                else:
                    spec = json.loads(content)

                system = generator.from_openapi(
                    spec=spec, system_name=state.get("system_name"), system_alias=state.get("system_alias")
                )
                state["generated_system"] = generator.to_dict(system)

                yield f"data: {json.dumps({'type': 'progress', 'message': 'Parsing complete', 'percent': 100})}\n\n"

            elif source_type == "har":
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Analyzing HAR file...', 'percent': 20})}\n\n"

                har_data = json.loads(state.get("har_content", "{}"))
                filter_domain = request.GET.get("domain", "")

                system = generator.from_har(
                    har_data=har_data,
                    system_name=state.get("system_name"),
                    system_alias=state.get("system_alias"),
                    filter_domain=filter_domain or None,
                )
                state["generated_system"] = generator.to_dict(system)

                yield f"data: {json.dumps({'type': 'progress', 'message': 'Analysis complete', 'percent': 100})}\n\n"

            elif source_type == "documentation":
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Fetching documentation...', 'percent': 10})}\n\n"
                yield f"data: {json.dumps({'type': 'progress', 'message': 'Analyzing with AI...', 'percent': 30})}\n\n"

                system = generator.from_documentation(
                    url=state.get("docs_url"),
                    system_name=state.get("system_name"),
                    system_alias=state.get("system_alias"),
                    base_url=state.get("base_url"),
                )
                state["generated_system"] = generator.to_dict(system)

                yield f"data: {json.dumps({'type': 'progress', 'message': 'AI analysis complete', 'percent': 100})}\n\n"

            elif source_type == "manual":
                # Manual mode - create empty structure
                state["generated_system"] = {
                    "name": state.get("system_name"),
                    "alias": state.get("system_alias"),
                    "display_name": state.get("system_name"),
                    "description": "",
                    "system_type": "other",
                    "interfaces": [
                        {
                            "name": "api",
                            "alias": "api",
                            "type": "API",
                            "base_url": state.get("base_url", ""),
                            "auth": {},
                            "resources": [],
                        }
                    ],
                }

                yield f"data: {json.dumps({'type': 'progress', 'message': 'Ready for manual configuration', 'percent': 100})}\n\n"

            # Save state
            save_wizard_state(request, state)

            # Build summary
            system_data = state.get("generated_system", {})
            interfaces = system_data.get("interfaces", [])
            total_resources = sum(len(i.get("resources", [])) for i in interfaces)
            total_actions = sum(len(r.get("actions", [])) for i in interfaces for r in i.get("resources", []))

            summary = {
                "type": "complete",
                "system_name": system_data.get("display_name", "Unknown"),
                "resources": total_resources,
                "actions": total_actions,
            }

            yield f"data: {json.dumps(summary)}\n\n"

        except Exception as e:
            logger.error(f"Discovery error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    return response


@login_required
@require_POST
def wizard_step2_submit(request):
    """Process Step 2 and move to Step 3.

    This also performs the actual discovery since SSE streaming
    doesn't reliably save session state.
    """
    from apps.systems.adapter_generator import AdapterGenerator

    state = get_wizard_state(request)
    source_type = state.get("source_type")

    try:
        generator = AdapterGenerator()

        if source_type == "openapi_url":
            system = generator.from_openapi(spec_url=state.get("openapi_url"))
            state["generated_system"] = generator.to_dict(system)

        elif source_type == "openapi_file":
            import yaml

            content = state.get("openapi_content", "{}")
            filename = state.get("openapi_filename", "spec.json")

            if filename.endswith((".yaml", ".yml")):
                spec = yaml.safe_load(content)
            else:
                spec = json.loads(content)

            system = generator.from_openapi(
                spec=spec, system_name=state.get("system_name"), system_alias=state.get("system_alias")
            )
            state["generated_system"] = generator.to_dict(system)

        elif source_type == "har":
            har_data = json.loads(state.get("har_content", "{}"))
            filter_domain = state.get("filter_domain", "")

            system = generator.from_har(
                har_data=har_data,
                system_name=state.get("system_name"),
                system_alias=state.get("system_alias"),
                filter_domain=filter_domain or None,
            )
            state["generated_system"] = generator.to_dict(system)

        elif source_type == "documentation":
            system = generator.from_documentation(
                url=state.get("docs_url"),
                system_name=state.get("system_name"),
                system_alias=state.get("system_alias"),
                base_url=state.get("base_url"),
            )
            state["generated_system"] = generator.to_dict(system)

        elif source_type == "manual":
            # Manual mode - create empty structure with one interface
            state["generated_system"] = {
                "name": state.get("system_name"),
                "alias": state.get("system_alias"),
                "display_name": state.get("system_name"),
                "description": "",
                "system_type": "other",
                "interfaces": [
                    {
                        "name": "api",
                        "alias": "api",
                        "type": "API",
                        "base_url": state.get("base_url", ""),
                        "auth": {},
                        "resources": [],
                    }
                ],
            }

        state["step"] = 3
        save_wizard_state(request, state)

        return redirect("wizard_step3")

    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        logger.error(f"Discovery error: {e}\n{error_details}")
        messages.error(request, f"Discovery failed: {str(e)}")

        # Store error in state for debugging
        state["last_error"] = str(e)
        state["last_error_details"] = error_details[:1000]  # Truncate for session storage
        save_wizard_state(request, state)

        return redirect("wizard_step2")


@login_required
def wizard_step3(request):
    """Step 3: Review & Edit endpoints."""
    state = get_wizard_state(request)

    if state["step"] < 3:
        return redirect("wizard_start")

    system_data = state.get("generated_system", {})

    context = {
        "state": state,
        "step": 3,
        "total_steps": 4,
        "system": system_data,
        "system_json": json.dumps(system_data, indent=2),
    }

    return render(request, "systems/wizard/step3_edit.html", context)


@login_required
@require_GET
def wizard_get_endpoint(request):
    """AJAX: Get endpoint details for editing."""
    state = get_wizard_state(request)

    resource_name = request.GET.get("resource")
    action_name = request.GET.get("action")

    system = state.get("generated_system", {})

    for interface in system.get("interfaces", []):
        for resource in interface.get("resources", []):
            if resource.get("name") == resource_name or resource.get("alias") == resource_name:
                for action in resource.get("actions", []):
                    if action.get("name") == action_name or action.get("alias") == action_name:
                        return JsonResponse(
                            {
                                "name": action.get("name", ""),
                                "alias": action.get("alias", ""),
                                "description": action.get("description", ""),
                                "method": action.get("method", "GET"),
                                "path": action.get("path", "/"),
                                "parameters": action.get("parameters_schema", {}).get("properties", {}),
                                "request_schema": action.get("request_body_schema"),
                                "response_schema": action.get("output_schema"),
                            }
                        )

    return JsonResponse({"error": "Endpoint not found"}, status=404)


@login_required
@require_POST
def wizard_delete_endpoint(request):
    """AJAX: Delete an endpoint."""
    state = get_wizard_state(request)

    try:
        data = json.loads(request.body)
        resource_name = data.get("resource")
        action_name = data.get("action")

        system = state.get("generated_system", {})

        for interface in system.get("interfaces", []):
            for resource in interface.get("resources", []):
                if resource.get("name") == resource_name or resource.get("alias") == resource_name:
                    actions = resource.get("actions", [])
                    resource["actions"] = [
                        a for a in actions if a.get("name") != action_name and a.get("alias") != action_name
                    ]
                    save_wizard_state(request, state)
                    return JsonResponse({"success": True})

        return JsonResponse({"error": "Endpoint not found"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def wizard_add_endpoint(request):
    """AJAX: Add a new endpoint to a resource."""
    state = get_wizard_state(request)

    try:
        data = json.loads(request.body)
        resource_name = data.get("resource")

        system = state.get("generated_system", {})

        # Ensure at least one interface exists
        if not system.get("interfaces"):
            system["interfaces"] = [
                {
                    "name": "api",
                    "alias": "api",
                    "type": "API",
                    "base_url": state.get("base_url", ""),
                    "auth": {},
                    "resources": [],
                }
            ]

        # Find or create resource
        target_resource = None
        target_interface = system["interfaces"][0]  # Use first interface

        for interface in system.get("interfaces", []):
            for resource in interface.get("resources", []):
                if resource.get("name") == resource_name or resource.get("alias") == resource_name:
                    target_resource = resource
                    target_interface = interface
                    break
            if target_resource:
                break

        # Create new resource if not found
        if not target_resource and resource_name:
            target_resource = {
                "name": resource_name,
                "alias": _slugify(resource_name),
                "description": "",
                "actions": [],
            }
            target_interface.setdefault("resources", []).append(target_resource)

        if target_resource:
            action_name = data.get("action_name", "new_action")
            target_resource.setdefault("actions", []).append(
                {
                    "name": action_name,
                    "alias": _slugify(action_name),
                    "description": data.get("description", ""),
                    "method": data.get("method", "GET"),
                    "path": data.get("path", "/"),
                    "parameters_schema": {"type": "object", "properties": {}},
                    "output_schema": {"type": "object"},
                }
            )

            save_wizard_state(request, state)
            return JsonResponse({"success": True})

        return JsonResponse({"error": "Could not create resource"}, status=400)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def wizard_update_endpoint(request):
    """AJAX: Update a single endpoint."""
    state = get_wizard_state(request)

    try:
        data = json.loads(request.body)

        resource_name = data.get("resource")
        original_action = data.get("original_action")

        system = state.get("generated_system", {})

        for interface in system.get("interfaces", []):
            for resource in interface.get("resources", []):
                if resource.get("name") == resource_name or resource.get("alias") == resource_name:
                    for action in resource.get("actions", []):
                        if action.get("name") == original_action or action.get("alias") == original_action:
                            # Update action
                            action["name"] = data.get("action_name", action.get("name"))
                            action["alias"] = _slugify(data.get("action_name", action.get("name")))
                            action["description"] = data.get("description", action.get("description"))
                            action["method"] = data.get("method", action.get("method"))
                            action["path"] = data.get("path", action.get("path"))

                            # Update parameters
                            if data.get("parameters"):
                                params = data["parameters"]
                                action["parameters_schema"] = {
                                    "type": "object",
                                    "properties": {
                                        p["name"]: {
                                            "type": p.get("type", "string"),
                                            "location": p.get("location", "query"),
                                        }
                                        for p in params
                                        if p.get("name")
                                    },
                                }

                            # Update schemas
                            if data.get("request_schema"):
                                try:
                                    action["request_body_schema"] = json.loads(data["request_schema"])
                                except json.JSONDecodeError:
                                    pass

                            if data.get("response_schema"):
                                try:
                                    action["output_schema"] = json.loads(data["response_schema"])
                                except json.JSONDecodeError:
                                    pass

                            save_wizard_state(request, state)
                            return JsonResponse({"success": True})

        return JsonResponse({"error": "Endpoint not found"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def wizard_add_resource(request):
    """AJAX: Add a new resource."""
    state = get_wizard_state(request)

    try:
        data = json.loads(request.body)
        interface_idx = data.get("interface_idx", 0)

        system = state.get("generated_system", {})
        interfaces = system.get("interfaces", [])

        if interface_idx < len(interfaces):
            interfaces[interface_idx].setdefault("resources", []).append(
                {
                    "name": data.get("name", "new_resource"),
                    "alias": data.get("alias", "new_resource"),
                    "description": data.get("description", ""),
                    "actions": [],
                }
            )

        save_wizard_state(request, state)

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def wizard_add_action(request):
    """AJAX: Add a new action to a resource."""
    state = get_wizard_state(request)

    try:
        data = json.loads(request.body)
        interface_idx = data.get("interface_idx", 0)
        resource_idx = data.get("resource_idx")

        system = state.get("generated_system", {})
        interfaces = system.get("interfaces", [])

        if interface_idx < len(interfaces):
            resources = interfaces[interface_idx].get("resources", [])

            if resource_idx is not None and resource_idx < len(resources):
                resources[resource_idx].setdefault("actions", []).append(
                    {
                        "name": data.get("name", "new_action"),
                        "alias": data.get("alias", "new_action"),
                        "description": data.get("description", ""),
                        "method": data.get("method", "GET"),
                        "path": data.get("path", "/"),
                        "parameters_schema": {},
                        "output_schema": {},
                    }
                )

        save_wizard_state(request, state)

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def wizard_delete_item(request):
    """AJAX: Delete a resource or action."""
    state = get_wizard_state(request)

    try:
        data = json.loads(request.body)
        interface_idx = data.get("interface_idx", 0)
        resource_idx = data.get("resource_idx")
        action_idx = data.get("action_idx")

        system = state.get("generated_system", {})
        interfaces = system.get("interfaces", [])

        if interface_idx < len(interfaces):
            resources = interfaces[interface_idx].get("resources", [])

            if action_idx is not None and resource_idx is not None:
                # Delete action
                if resource_idx < len(resources):
                    actions = resources[resource_idx].get("actions", [])
                    if action_idx < len(actions):
                        actions.pop(action_idx)
            elif resource_idx is not None:
                # Delete resource
                if resource_idx < len(resources):
                    resources.pop(resource_idx)

        save_wizard_state(request, state)

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def wizard_step3_submit(request):
    """Process Step 3 and move to Step 4."""
    state = get_wizard_state(request)

    # Save any final edits from the form
    if request.POST.get("system_json"):
        try:
            system_data = json.loads(request.POST.get("system_json"))
            state["generated_system"] = system_data
        except json.JSONDecodeError:
            messages.error(request, "Invalid JSON")
            return redirect("wizard_step3")

    state["step"] = 4
    save_wizard_state(request, state)

    return redirect("wizard_step4")


@login_required
def wizard_step4(request):
    """Step 4: Test & Save."""
    state = get_wizard_state(request)

    if state["step"] < 4:
        return redirect("wizard_start")

    system_data = state.get("generated_system", {})

    # Calculate summary
    interfaces = system_data.get("interfaces", [])
    total_resources = sum(len(i.get("resources", [])) for i in interfaces)
    total_actions = sum(len(r.get("actions", [])) for i in interfaces for r in i.get("resources", []))

    context = {
        "state": state,
        "step": 4,
        "total_steps": 4,
        "system": system_data,
        "summary": {
            "name": system_data.get("display_name"),
            "alias": system_data.get("alias"),
            "type": system_data.get("system_type"),
            "interfaces": len(interfaces),
            "resources": total_resources,
            "actions": total_actions,
        },
    }

    return render(request, "systems/wizard/step4_save.html", context)


@login_required
@require_POST
def wizard_test_connection(request):
    """AJAX: Test connection to the API."""
    import asyncio

    from apps.systems.discovery import LiveDiscovery

    state = get_wizard_state(request)
    system_data = state.get("generated_system", {})

    try:
        data = json.loads(request.body)
        base_url = data.get("base_url", "")
        auth_data = data.get("auth", {})

        # Build auth headers
        auth_headers = {}
        auth_type = auth_data.get("type", "none")

        if auth_type == "bearer":
            token = auth_data.get("token", "")
            if token:
                auth_headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key_name = auth_data.get("key_name", "X-API-Key")
            key_value = auth_data.get("key_value", "")
            key_location = auth_data.get("key_location", "header")
            if key_value and key_location == "header":
                auth_headers[key_name] = key_value
        elif auth_type == "basic":
            import base64

            username = auth_data.get("username", "")
            password = auth_data.get("password", "")
            if username:
                credentials = f"{username}:{password}"
                auth_headers["Authorization"] = f"Basic {base64.b64encode(credentials.encode()).decode()}"

        if not base_url:
            interfaces = system_data.get("interfaces", [])
            if interfaces:
                base_url = interfaces[0].get("base_url", "")

        if not base_url:
            return JsonResponse(
                {"tests": [{"method": "GET", "path": "/", "success": False, "message": "No base URL defined"}]}
            )

        # Test endpoints
        async def run_tests():
            test_results = []
            interfaces = system_data.get("interfaces", [])

            try:
                async with LiveDiscovery(base_url=base_url, auth_headers=auth_headers) as discovery:
                    for interface in interfaces[:1]:
                        for resource in interface.get("resources", [])[:3]:
                            for action in resource.get("actions", [])[:2]:
                                method = action.get("method", "GET")
                                if method == "GET":  # Only test GET for safety
                                    path = action.get("path", "/")
                                    # Replace path params with test values
                                    import re

                                    path = re.sub(r"\{[^}]+\}", "1", path)

                                    result = await discovery.probe_endpoint("GET", path)
                                    test_results.append(
                                        {
                                            "method": method,
                                            "path": path,
                                            "success": result.status.value in ("success", "warning"),
                                            "status_code": result.http_status,
                                            "message": result.error_message or f"OK ({result.response_time_ms}ms)",
                                        }
                                    )

                    # If no endpoints found, test base URL
                    if not test_results:
                        result = await discovery.probe_endpoint("GET", "/")
                        test_results.append(
                            {
                                "method": "GET",
                                "path": "/",
                                "success": result.status.value in ("success", "warning"),
                                "status_code": result.http_status,
                                "message": result.error_message or f"OK ({result.response_time_ms}ms)",
                            }
                        )

            except Exception as e:
                test_results.append({"method": "GET", "path": "/", "success": False, "message": str(e)})

            return test_results

        results = asyncio.run(run_tests())

        return JsonResponse({"tests": results})

    except Exception as e:
        logger.error(f"Connection test error: {e}")
        return JsonResponse({"tests": [{"method": "GET", "path": "/", "success": False, "message": str(e)}]})


@login_required
@require_POST
def wizard_save(request):
    """Save the adapter to database."""
    from apps.systems.adapter_generator import AdapterGenerator, GeneratedSystem

    state = get_wizard_state(request)
    active_account = get_active_account(request)

    system_data = state.get("generated_system", {})

    if not system_data:
        messages.error(request, "No system data to save.")
        return redirect("wizard_step4")

    try:
        # Reconstruct GeneratedSystem from dict
        generator = AdapterGenerator(account_id=active_account.id)

        # Convert dict back to dataclass (simplified)
        from apps.systems.adapter_generator import (
            GeneratedAction,
            GeneratedInterface,
            GeneratedResource,
            GeneratedSystem,
        )

        interfaces = []
        for iface_data in system_data.get("interfaces", []):
            resources = []
            for res_data in iface_data.get("resources", []):
                actions = []
                for act_data in res_data.get("actions", []):
                    actions.append(
                        GeneratedAction(
                            name=act_data.get("name", ""),
                            alias=act_data.get("alias", ""),
                            description=act_data.get("description", ""),
                            method=act_data.get("method", "GET"),
                            path=act_data.get("path", "/"),
                            parameters_schema=act_data.get("parameters_schema", {}),
                            output_schema=act_data.get("output_schema", {}),
                        )
                    )

                resources.append(
                    GeneratedResource(
                        name=res_data.get("name", ""),
                        alias=res_data.get("alias", ""),
                        description=res_data.get("description", ""),
                        actions=actions,
                    )
                )

            interfaces.append(
                GeneratedInterface(
                    name=iface_data.get("name", "api"),
                    alias=iface_data.get("alias", "api"),
                    type=iface_data.get("type", "API"),
                    base_url=iface_data.get("base_url", ""),
                    auth=iface_data.get("auth", {}),
                    resources=resources,
                )
            )

        system = GeneratedSystem(
            name=system_data.get("name", ""),
            alias=system_data.get("alias", ""),
            display_name=system_data.get("display_name", ""),
            description=system_data.get("description", ""),
            system_type=system_data.get("system_type", "other"),
            website_url=system_data.get("website_url", ""),
            variables=system_data.get("variables", {}),
            interfaces=interfaces,
        )

        # Save to database
        db_system = generator.save_to_database(system, active_account.id)

        # Persist spec URL and initial digest for future refresh
        if state.get("source_type") == "openapi_url" and state.get("openapi_url"):
            import hashlib

            if not db_system.meta:
                db_system.meta = {}
            db_system.meta["openapi_spec_url"] = state["openapi_url"]
            # Compute initial schema digest from the generated system dict
            canonical = json.dumps(state["generated_system"], sort_keys=True, separators=(",", ":"))
            db_system.schema_digest = hashlib.sha256(canonical.encode()).hexdigest()
            db_system.save(update_fields=["meta", "schema_digest"])

        # Clear wizard state
        clear_wizard_state(request)

        messages.success(request, f"System '{db_system.display_name}' created successfully!")

        return redirect("interfaces_list", system_id=db_system.id)

    except Exception as e:
        logger.error(f"Save error: {e}", exc_info=True)
        messages.error(request, f"Failed to save: {str(e)}")
        return redirect("wizard_step4")


def _slugify(text: str) -> str:
    """Convert text to slug."""
    import re

    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")
