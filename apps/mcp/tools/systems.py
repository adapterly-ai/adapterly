"""
MCP System Tools - Auto-generated from Action definitions.

These tools provide direct access to integrated systems:
- Read operations (system_read): List, get, search
- Write operations (system_write): Create, update, delete

Tool names follow the pattern: {system}_{resource}_{action}
Example: salesforce_contact_create, hubspot_deal_update
"""

import logging
import re
from typing import Any

from asgiref.sync import sync_to_async

from apps.mcp.tools.base import MCPTool

logger = logging.getLogger(__name__)

# Path parameter names that represent a project/workspace identifier.
# When a project has an external_id for a system, these params are auto-resolved.
_PROJECT_PARAM_NAMES = frozenset(
    {
        "project_id",
        "projectId",
        "project_key",
        "projectKey",
        "projectIdOrKey",
        "project",
        "workspace_id",
        "workspaceId",
        "repo",
        "repository",
        "repo_slug",
    }
)


def _build_project_context(project_id: int) -> tuple[dict[str, str], dict[str, list[str] | None]]:
    """Build project context from ProjectIntegrations.

    Returns:
        Tuple of:
        - external_ids: {system_alias: external_id} for path-param auto-injection
        - allowed_actions: {system_alias: list_of_tool_names | None} for per-tool filtering
          None means all tools allowed for that system.
    """
    from apps.mcp.models import ProjectIntegration

    external_ids = {}
    allowed_actions = {}
    for pi in ProjectIntegration.objects.filter(project_id=project_id, is_enabled=True).select_related("system"):
        if pi.external_id:
            external_ids[pi.system.alias] = pi.external_id
        allowed_actions[pi.system.alias] = pi.allowed_actions
    return external_ids, allowed_actions


def get_system_tools(account_id: int, project_id: int | None = None) -> list[MCPTool]:
    """
    Generate MCP tools from Action definitions.

    When project_id is provided, only tools for systems linked via
    ProjectIntegration are included. Per-tool filtering is applied
    if the integration has allowed_actions set.

    Args:
        account_id: Account ID to generate tools for
        project_id: Optional project ID — scopes tools to project integrations

    Returns:
        List of MCPTool objects
    """
    from apps.systems.models import AccountSystem, Action

    tools = []
    project_context: dict[str, str] = {}
    project_allowed: dict[str, list[str] | None] = {}

    if project_id:
        project_context, project_allowed = _build_project_context(project_id)

    try:
        if project_id and project_allowed:
            # Project-scoped: only systems linked via ProjectIntegration
            enabled_systems = list(project_allowed.keys())
        else:
            # No project binding: all account-level systems
            enabled_systems = list(
                AccountSystem.objects.filter(account_id=account_id, is_enabled=True).values_list(
                    "system__alias", flat=True
                )
            )

        if not enabled_systems:
            logger.info(f"No enabled systems for account {account_id}")
            return tools

        # Get all MCP-enabled actions for enabled systems
        actions = list(
            Action.objects.filter(
                resource__interface__system__alias__in=enabled_systems,
                resource__interface__system__is_active=True,
                is_mcp_enabled=True,  # Only include actions marked for MCP exposure
            ).select_related("resource__interface__system")
        )

        for action in actions:
            tool = _action_to_tool(action, account_id, project_context)
            if tool:
                # Per-tool filtering: if allowed_actions is set, only include listed tools
                system_alias = tool.system_alias
                if system_alias and system_alias in project_allowed:
                    allowed = project_allowed[system_alias]
                    if allowed is not None and tool.name not in allowed:
                        continue
                tools.append(tool)

        logger.info(f"Generated {len(tools)} system tools for account {account_id} (project={project_id})")
    except Exception as e:
        logger.warning(f"Error generating system tools: {e}")

    return tools


def _action_to_tool(action, account_id: int, project_context: dict[str, str] | None = None) -> MCPTool | None:
    """
    Convert an Action to an MCPTool.
    """
    try:
        system = action.resource.interface.system
        resource = action.resource

        # Build tool name: {prefix}_{resource}_{action}
        prefix = system.mcp_prefix or system.alias
        tool_name = f"{prefix}_{resource.alias}_{action.alias}"
        tool_name = _sanitize_tool_name(tool_name)

        # Determine tool type based on HTTP method
        method = action.method.upper()
        if method in ("GET", "HEAD", "OPTIONS"):
            tool_type = "system_read"
        else:
            tool_type = "system_write"

        # Build description
        description = action.description or f"{action.name} on {system.display_name} {resource.name}"

        # Determine auto-inject params from project context
        auto_inject = {}
        external_id = (project_context or {}).get(system.alias)
        if external_id:
            path = action.path or ""
            path_params = re.findall(r"\{(\w+)\}", path)
            for param in path_params:
                if param in _PROJECT_PARAM_NAMES:
                    auto_inject[param] = external_id
                    break  # Only inject the first matching project param

        # Build input schema from action parameters
        input_schema = _build_action_input_schema(action, auto_inject)

        if auto_inject:
            injected_names = ", ".join(auto_inject.keys())
            description = f"{description} ({injected_names} auto-resolved from project context)"

        # Create handler function
        handler = _create_action_handler(
            action_id=action.id,
            system_alias=system.alias,
            interface_alias=action.resource.interface.alias,
            resource_alias=resource.alias,
            action_alias=action.alias,
            method=method,
            auto_inject=auto_inject or None,
        )

        return MCPTool(
            name=tool_name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            tool_type=tool_type,
            output_schema=action.output_schema,
            examples=action.examples or [],
            system_alias=system.alias,
            action_alias=action.alias,
        )

    except Exception as e:
        logger.error(f"Failed to convert action {action} to tool: {e}")
        return None


def _sanitize_tool_name(name: str) -> str:
    """Sanitize tool name to be MCP-compliant."""
    # Replace non-alphanumeric with underscore
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Remove consecutive underscores
    name = re.sub(r"_+", "_", name)
    # Remove leading/trailing underscores
    name = name.strip("_")
    # Convert to lowercase
    name = name.lower()
    return name


def _build_action_input_schema(action, auto_inject: dict[str, str] | None = None) -> dict[str, Any]:
    """Build JSON Schema from action parameters.

    Args:
        action: Action model instance
        auto_inject: Dict of param_name → value that will be auto-injected
                     at execution time. These are removed from the schema
                     so the agent doesn't need to provide them.
    """
    if action.parameters_schema:
        # Use the existing schema
        schema = action.parameters_schema.copy()

        # Ensure it has the right structure
        if "type" not in schema:
            schema["type"] = "object"

        # Remove auto-injected params from explicit schema
        if auto_inject and "properties" in schema:
            for param in auto_inject:
                schema["properties"].pop(param, None)
                if "required" in schema and param in schema["required"]:
                    schema["required"] = [r for r in schema["required"] if r != param]

        return schema

    # Build from path parameters
    path = action.path or ""
    path_params = re.findall(r"\{(\w+)\}", path)

    properties = {}
    required = []

    for param in path_params:
        if auto_inject and param in auto_inject:
            continue  # Skip — will be auto-injected
        properties[param] = {"type": "string", "description": f"Path parameter: {param}"}
        required.append(param)

    # Add request body for write operations
    if action.method.upper() in ("POST", "PUT", "PATCH"):
        properties["data"] = {"type": "object", "description": "Request body data"}

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return schema


def _create_action_handler(
    action_id: int,
    system_alias: str,
    interface_alias: str,
    resource_alias: str,
    action_alias: str,
    method: str,
    auto_inject: dict[str, str] | None = None,
):
    """
    Create a handler function for an action.

    Args:
        auto_inject: Dict of param_name → value to inject automatically
                     before path substitution (e.g. project_id from project context).

    Returns an async function that executes the action.
    """

    async def handler(ctx: dict[str, Any], **params) -> dict[str, Any]:
        """Execute the system action."""
        from apps.systems.models import AccountSystem, Action

        account_id = ctx["account_id"]
        session_manager = ctx.get("session_manager")

        # Inject auto-resolved params (e.g. project_id from project context)
        if auto_inject:
            for key, value in auto_inject.items():
                if key not in params:
                    params[key] = value

        try:
            # Get the action (wrapped for async)
            @sync_to_async
            def get_action_data():
                action = Action.objects.select_related("resource__interface__system").get(id=action_id)
                return {
                    "action": action,
                    "interface": action.resource.interface,
                    "system": action.resource.interface.system,
                    "path": action.path,
                    "headers": action.headers or {},
                }

            action_data = await get_action_data()
            interface = action_data["interface"]
            system = action_data["system"]

            # Get authentication
            auth_headers = {}

            # Try session manager first
            if session_manager:
                session = await session_manager.get_session(system_alias, interface_alias)
                if session and session.is_authenticated:
                    auth_headers = session.auth_headers

            # If no session auth, try AccountSystem
            if not auth_headers:

                @sync_to_async
                def get_account_system():
                    try:
                        return AccountSystem.objects.get(account_id=account_id, system_id=system.id, is_enabled=True)
                    except AccountSystem.DoesNotExist:
                        return None

                account_system = await get_account_system()

                if account_system is None:
                    return {"error": f"System {system_alias} not configured for this account"}

                # Check if interface uses OAuth password grant
                auth_config = interface.auth or {}
                if auth_config.get("type") == "oauth2_password":
                    auth_headers = await _get_oauth_token(account_system, auth_config)
                else:
                    # Use standard auth headers
                    @sync_to_async
                    def get_headers():
                        return account_system.get_auth_headers()

                    auth_headers = await get_headers()

            if not auth_headers:
                return {"error": f"Not authenticated to {system_alias}"}

            # Build request
            path = _substitute_path_params(action_data["path"], params)
            url = f"{interface.base_url.rstrip('/')}/{path.lstrip('/')}"

            # Extract body data
            data = params.pop("data", None)

            # Execute based on method
            if method in ("GET", "HEAD", "OPTIONS"):
                result = await _execute_read(
                    url=url,
                    method=method,
                    params=params,
                    headers={**action_data["headers"], **auth_headers},
                    action=action_data["action"],
                )
            else:
                result = await _execute_write(
                    url=url,
                    method=method,
                    data=data or params,
                    headers={**action_data["headers"], **auth_headers},
                    action=action_data["action"],
                )

            return result

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return {"error": str(e)}

    return handler


async def _get_oauth_token(account_system, auth_config: dict) -> dict[str, str]:
    """
    Get OAuth token using password grant.
    Uses cached token if still valid, otherwise fetches new one.
    """
    from datetime import timedelta

    import requests
    from django.utils import timezone

    # Get account system data synchronously
    @sync_to_async
    def get_cached_token_info():
        return {
            "oauth_token": account_system.oauth_token,
            "is_expired": account_system.is_oauth_expired(),
            "username": account_system.username,
            "password": account_system.password,
            "system_alias": account_system.system.alias,
        }

    cached_info = await get_cached_token_info()

    # Check if we have a valid cached token
    if cached_info["oauth_token"] and not cached_info["is_expired"]:
        return {"Authorization": f"Bearer {cached_info['oauth_token']}"}

    # Need to get a new token
    token_url = auth_config.get("token_url")
    if not token_url:
        logger.error("No token_url in auth config")
        return {}

    username = cached_info["username"]
    password = cached_info["password"]

    if not username or not password:
        logger.error("No username/password configured for OAuth")
        return {}

    try:
        response = requests.post(
            token_url,
            data={"grant_type": auth_config.get("grant_type", "password"), "username": username, "password": password},
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(f"OAuth token request failed: {response.status_code} - {response.text}")
            return {}

        data = response.json()

        token_field = auth_config.get("token_field", "access_token")
        expires_field = auth_config.get("expires_field", "expires_in")

        token = data.get(token_field)
        if not token:
            logger.error(f"No {token_field} in OAuth response: {data}")
            return {}

        # Cache the token
        expires_in = data.get(expires_field, 3600)

        @sync_to_async
        def save_token():
            account_system.oauth_token = token
            account_system.oauth_expires_at = timezone.now() + timedelta(seconds=expires_in - 300)
            account_system.save(update_fields=["oauth_token", "oauth_expires_at"])

        await save_token()

        logger.info(f"Obtained OAuth token for {cached_info['system_alias']}")

        return {"Authorization": f"Bearer {token}"}

    except Exception as e:
        logger.error(f"OAuth token request failed: {e}")
        return {}


def _substitute_path_params(path: str, params: dict) -> str:
    """Substitute path parameters in URL."""
    if not path:
        return ""

    result = path
    for key, value in list(params.items()):
        placeholder = f"{{{key}}}"
        if placeholder in result:
            result = result.replace(placeholder, str(value))
            del params[key]  # Remove used path params

    return result


async def _execute_read(url: str, method: str, params: dict, headers: dict, action) -> dict[str, Any]:
    """Execute a read operation with optional pagination support."""
    import requests

    # Check if action has pagination config and user wants all pages
    pagination_config = getattr(action, "pagination", None) or {}
    fetch_all = params.pop("fetch_all_pages", False)

    if fetch_all and pagination_config:
        return await _execute_paginated_read(url, method, params, headers, pagination_config)

    try:
        response = requests.request(method=method, url=url, params=params, headers=headers, timeout=30)

        response.raise_for_status()

        # Try to parse as JSON
        try:
            data = response.json()
        except Exception:
            data = {"text": response.text}

        return {"success": True, "status_code": response.status_code, "data": data}

    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": str(e), "status_code": e.response.status_code if e.response else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_paginated_read(
    url: str, method: str, params: dict, headers: dict, pagination_config: dict
) -> dict[str, Any]:
    """Execute paginated read, fetching all pages automatically."""
    import time

    import requests

    # Pagination config fields
    page_param = pagination_config.get("page_param", "page")
    size_param = pagination_config.get("size_param", "pageSize")
    default_size = pagination_config.get("default_size", 100)
    max_size = pagination_config.get("max_size", 100)
    start_page = pagination_config.get("start_page", 1)

    # Response field mappings
    data_field = pagination_config.get("data_field", None)
    total_pages_field = pagination_config.get("total_pages_field", "totalPages")
    last_page_field = pagination_config.get("last_page_field", "last")

    # Safety limits to prevent infinite loops
    max_pages = pagination_config.get("max_pages", 50)
    max_items = pagination_config.get("max_items", 10000)
    max_time_seconds = pagination_config.get("max_time_seconds", 120)
    max_empty_pages = 3  # Stop after N consecutive empty pages

    all_items = []
    current_page = start_page
    start_time = time.time()
    empty_page_count = 0
    prev_total_items = 0

    try:
        while True:
            # Safety check: max pages
            if current_page - start_page >= max_pages:
                logger.warning(f"Pagination stopped: max pages ({max_pages}) reached")
                break

            # Safety check: max items
            if len(all_items) >= max_items:
                logger.warning(f"Pagination stopped: max items ({max_items}) reached")
                break

            # Safety check: timeout
            elapsed = time.time() - start_time
            if elapsed > max_time_seconds:
                logger.warning(f"Pagination stopped: timeout ({max_time_seconds}s) reached")
                break

            page_params = {**params, page_param: current_page, size_param: min(default_size, max_size)}

            response = requests.request(method=method, url=url, params=page_params, headers=headers, timeout=60)

            response.raise_for_status()
            data = response.json()

            # Extract items from response
            if data_field and data_field in data:
                items = data[data_field]
            elif isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = None
                for field in ["content", "items", "data", "results", "records"]:
                    if field in data and isinstance(data[field], list):
                        items = data[field]
                        break
                if items is None:
                    items = []
            else:
                items = []

            # Safety check: no progress (same items returned)
            if len(items) == 0:
                empty_page_count += 1
                if empty_page_count >= max_empty_pages:
                    logger.warning(f"Pagination stopped: {max_empty_pages} consecutive empty pages")
                    break
            else:
                empty_page_count = 0

            all_items.extend(items)

            # Safety check: no new items added (potential duplicate page)
            if len(all_items) == prev_total_items and len(items) > 0:
                logger.warning("Pagination stopped: no new items (possible duplicate page)")
                break
            prev_total_items = len(all_items)

            # Check if last page based on API response
            is_last = False
            if isinstance(data, dict):
                if last_page_field in data:
                    is_last = bool(data[last_page_field])
                elif total_pages_field in data:
                    total_pages = data.get(total_pages_field, 0)
                    is_last = current_page >= total_pages
                elif len(items) < default_size:
                    is_last = True

            if is_last:
                logger.debug(f"Pagination complete: last page indicator at page {current_page}")
                break

            current_page += 1

        elapsed = time.time() - start_time
        return {
            "success": True,
            "status_code": 200,
            "data": all_items,
            "pagination": {
                "total_items": len(all_items),
                "pages_fetched": current_page - start_page + 1,
                "elapsed_seconds": round(elapsed, 2),
            },
        }

    except requests.exceptions.HTTPError as e:
        return {
            "success": False,
            "error": str(e),
            "status_code": e.response.status_code if e.response else None,
            "partial_data": all_items if all_items else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "partial_data": all_items if all_items else None}


async def _execute_write(url: str, method: str, data: dict, headers: dict, action) -> dict[str, Any]:
    """Execute a write operation."""
    import requests

    try:
        # Determine content type
        content_type = headers.get("Content-Type", "application/json")

        if "json" in content_type:
            response = requests.request(method=method, url=url, json=data, headers=headers, timeout=30)
        else:
            response = requests.request(method=method, url=url, data=data, headers=headers, timeout=30)

        response.raise_for_status()

        # Try to parse response
        try:
            result_data = response.json()
        except Exception:
            result_data = {"text": response.text} if response.text else {}

        return {"success": True, "status_code": response.status_code, "data": result_data}

    except requests.exceptions.HTTPError as e:
        error_data = None
        if e.response is not None:
            try:
                error_data = e.response.json()
            except Exception:
                error_data = {"text": e.response.text}

        return {
            "success": False,
            "error": str(e),
            "status_code": e.response.status_code if e.response else None,
            "error_data": error_data,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def refresh_system_tools(registry, account_id: int):
    """
    Refresh system tools in the registry.

    Call this when systems or actions are added/removed.
    """
    # Remove existing system tools
    to_remove = [name for name, tool in registry._tools.items() if tool.tool_type in ("system_read", "system_write")]
    for name in to_remove:
        registry.unregister(name)

    # Add fresh tools
    for tool in get_system_tools(account_id):
        registry.register(tool)

    logger.info(f"Refreshed system tools for account {account_id}")
