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
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...crypto import encrypt_value
from ...models.mcp import ProjectIntegration
from ...models.systems import AccountSystem, Action, Interface, Resource, System
from .diagnostics import diagnose_error, persist_diagnostic

logger = logging.getLogger(__name__)


async def _confirm_system_if_needed(db: AsyncSession, system: System) -> None:
    """
    Mark system as confirmed after first successful API call.

    This is called when an API call succeeds, indicating the integration works.
    """
    if not system.is_confirmed:
        try:
            system.is_confirmed = True
            system.confirmed_at = datetime.utcnow()
            await db.commit()
            logger.info(f"System '{system.alias}' confirmed as working")
        except Exception as e:
            logger.warning(f"Failed to confirm system '{system.alias}': {e}")
            await db.rollback()


async def get_system_tools(db: AsyncSession, account_id: int, project_id: int | None = None) -> list[dict[str, Any]]:
    """
    Generate MCP tools from Action definitions.

    System tools are scoped by ProjectIntegration:
    - If project_id is set, only systems with an enabled ProjectIntegration are shown
    - If project_id is None (admin token), no system tools are returned

    Args:
        db: Database session
        account_id: Account ID to generate tools for
        project_id: Optional project ID to scope systems

    Returns:
        List of tool definitions
    """
    tools = []

    if project_id is None:
        # Admin token or no project → no system tools
        return tools

    try:
        # Get enabled systems via ProjectIntegration for this project
        integration_stmt = (
            select(ProjectIntegration.system_id)
            .where(ProjectIntegration.project_id == project_id)
            .where(ProjectIntegration.is_enabled == True)  # noqa: E712
        )
        result = await db.execute(integration_stmt)
        enabled_system_ids = [row[0] for row in result.fetchall()]

        if not enabled_system_ids:
            logger.info(f"No enabled integrations for project {project_id}")
            return tools

        # Get all MCP-enabled actions for enabled systems
        actions_stmt = (
            select(Action)
            .join(Resource)
            .join(Interface)
            .join(System)
            .options(selectinload(Action.resource).selectinload(Resource.interface).selectinload(Interface.system))
            .where(System.id.in_(enabled_system_ids))
            .where(System.is_active == True)  # noqa: E712
            .where(Action.is_mcp_enabled == True)  # noqa: E712
        )

        result = await db.execute(actions_stmt)
        actions = result.scalars().all()

        for action in actions:
            tool = _action_to_tool(action)
            if tool:
                tools.append(tool)

        logger.info(f"Generated {len(tools)} system tools for project {project_id}")

    except Exception as e:
        logger.warning(f"Error generating system tools: {e}")

    return tools


def _action_to_tool(action: Action) -> dict[str, Any] | None:
    """Convert an Action to a tool definition."""
    try:
        resource = action.resource
        interface = resource.interface
        system = interface.system

        # Build tool name: {system}_{resource}_{action}
        tool_name = f"{system.alias}_{resource.alias or resource.name}_{action.alias or action.name}"
        tool_name = _sanitize_tool_name(tool_name)

        # Determine tool type based on HTTP method and interface type
        method = action.method.upper()
        interface_type = interface.type.upper()

        if interface_type == "GRAPHQL":
            # GraphQL: queries are read, mutations are write
            # Check if action name suggests mutation
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

        # Build description
        description = action.description or f"{action.name} on {system.display_name} {resource.name}"
        if action.pagination:
            description += (
                " (paginated: returns summary with count, columns and 3 sample items."
                " Use 'page: N' for full page data, 'fetch_all_pages: true' to store all as dataset pointer)"
            )

        # Build input schema from action parameters
        input_schema = _build_action_input_schema(action, interface_type)

        return {
            "name": tool_name,
            "description": description,
            "input_schema": input_schema,
            "tool_type": tool_type,
            "system_alias": system.alias,
            "action_id": action.id,
            "method": method,
            "interface_type": interface_type,
            "interface_alias": interface.alias or interface.name,
            "resource_alias": resource.alias or resource.name,
            "action_alias": action.alias or action.name,
        }

    except Exception as e:
        logger.error(f"Failed to convert action {action} to tool: {e}")
        return None


def _sanitize_tool_name(name: str) -> str:
    """Sanitize tool name to be MCP-compliant."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    name = name.lower()
    return name


def _build_action_input_schema(action: Action, interface_type: str = "API") -> dict[str, Any]:
    """Build JSON Schema from action parameters."""
    if action.parameters_schema:
        schema = dict(action.parameters_schema)
        if "type" not in schema:
            schema["type"] = "object"
        # Add pagination controls for paginated actions
        if action.pagination:
            props = dict(schema.get("properties", {}))
            props["page"] = {
                "type": "integer",
                "description": "Page number to fetch (0-indexed). Default: 0 (first page).",
            }
            props["fetch_all_pages"] = {
                "type": "boolean",
                "description": "Set to true to fetch ALL pages and return combined results. Warning: can be slow for large datasets.",
                "default": False,
            }
            schema["properties"] = props
        return schema

    # GraphQL interface: different schema structure
    if interface_type == "GRAPHQL":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "GraphQL query or mutation string"},
                "variables": {
                    "type": "object",
                    "description": "Variables for the GraphQL query",
                    "additionalProperties": True,
                },
                "operation_name": {
                    "type": "string",
                    "description": "Optional operation name if query contains multiple operations",
                },
            },
            "required": ["query"],
        }

    # Build from path parameters
    path = action.path or ""
    path_params = re.findall(r"\{(\w+)\}", path)

    properties = {}
    required = []

    for param in path_params:
        properties[param] = {"type": "string", "description": f"Path parameter: {param}"}
        required.append(param)

    # Add request body for write operations
    if action.method.upper() in ("POST", "PUT", "PATCH"):
        properties["data"] = {"type": "object", "description": "Request body data"}

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return schema


async def execute_system_tool(
    db: AsyncSession,
    action_id: int,
    account_id: int,
    params: dict[str, Any],
    project_id: int | None = None,
) -> dict[str, Any]:
    """
    Execute a system tool action.

    Credential resolution and external_id are driven by ProjectIntegration:
    - integration.credential_source determines which AccountSystem to use
    - integration.external_id is injected as project filter

    Args:
        db: Database session
        action_id: Action ID to execute
        account_id: Account ID for authentication
        params: Tool parameters
        project_id: Project ID for integration lookup

    Returns:
        Execution result
    """
    try:
        # Get action with related data
        action_stmt = (
            select(Action)
            .options(selectinload(Action.resource).selectinload(Resource.interface).selectinload(Interface.system))
            .where(Action.id == action_id)
        )
        result = await db.execute(action_stmt)
        action = result.scalar_one_or_none()

        if not action:
            return {"error": f"Action {action_id} not found"}

        interface = action.resource.interface
        system = interface.system

        # Get ProjectIntegration for this project+system
        integration = None
        if project_id is not None:
            integration_stmt = (
                select(ProjectIntegration)
                .where(ProjectIntegration.project_id == project_id)
                .where(ProjectIntegration.system_id == system.id)
                .where(ProjectIntegration.is_enabled == True)  # noqa: E712
            )
            result = await db.execute(integration_stmt)
            integration = result.scalar_one_or_none()

        if not integration:
            return {"error": f"System {system.alias} not configured for this project"}

        # Credential resolution based on integration.credential_source
        account_system_stmt = (
            select(AccountSystem)
            .options(selectinload(AccountSystem.system))
            .where(AccountSystem.account_id == account_id)
            .where(AccountSystem.system_id == system.id)
            .where(AccountSystem.is_enabled == True)  # noqa: E712
        )
        if integration.credential_source == "project":
            # Project-specific credentials
            account_system_stmt = account_system_stmt.where(AccountSystem.project_id == project_id)
        else:
            # Account-level shared credentials
            account_system_stmt = account_system_stmt.where(
                AccountSystem.project_id == None  # noqa: E711
            )
        result = await db.execute(account_system_stmt)
        account_system = result.scalars().first()

        if not account_system:
            return {"error": f"No credentials found for {system.alias} (source: {integration.credential_source})"}

        # Determine retry capability based on auth type
        auth_config = interface.auth or {}
        auth_type = auth_config.get("type", "")
        max_attempts = 2 if auth_type in ("drf_token", "oauth2_password") else 1

        # Save original params before mutation by inject/substitute
        original_params = dict(params)
        method = action.method.upper()
        external_id = integration.external_id or None
        interface_type = interface.type.upper()

        result = None
        for attempt in range(max_attempts):
            force_refresh = attempt > 0  # Force refresh on retry

            # Get authentication headers
            auth_headers = await _get_auth_headers(account_system, interface, db, force_refresh=force_refresh)
            if not auth_headers:
                return {"error": f"Not authenticated to {system.alias}"}

            # Copy params for each attempt (path substitution mutates them)
            attempt_params = dict(original_params)

            # Auto-inject project filter using external_id from ProjectIntegration
            if external_id:
                attempt_params = _inject_project_filter(action, attempt_params, external_id, method)

            # Build request
            path = _substitute_path_params(action.path, attempt_params)
            url = f"{interface.base_url.rstrip('/')}/{path.lstrip('/')}"

            # Extract body data
            data = attempt_params.pop("data", None)

            # Merge headers
            headers = {**(action.headers or {}), **auth_headers}

            # Execute request - route based on interface type
            if interface_type == "GRAPHQL":
                result = await _execute_graphql(url=url, params=attempt_params, data=data, headers=headers, action=action)
            elif method in ("GET", "HEAD", "OPTIONS"):
                result = await _execute_read(
                    url=url,
                    method=method,
                    params=attempt_params,
                    headers=headers,
                    action=action,
                    account_id=account_id,
                    source_info={
                        "system": system.alias,
                        "resource": action.resource.alias or action.resource.name,
                        "action": action.alias or action.name,
                    },
                )
            else:
                result = await _execute_write(url=url, method=method, data=data or attempt_params, headers=headers)

            # Check if we should retry (401/502 on non-last attempt)
            status_code = result.get("status_code")
            if attempt < max_attempts - 1 and status_code in (401, 502):
                logger.info(
                    f"Got {status_code} from {system.alias}, refreshing token and retrying "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )
                continue

            # No retry needed or last attempt
            break

        # Confirm system as working after successful API call
        if "error" not in result:
            await _confirm_system_if_needed(db, system)
        else:
            # Diagnose the error and attach diagnostic info
            try:
                action_name = action.alias or action.name
                diag = diagnose_error(
                    system_alias=system.alias,
                    tool_name=f"{system.alias}_{action_name}",
                    action_name=action_name,
                    error_result=result,
                    account_system=account_system,
                    request_params=original_params,
                )
                if diag:
                    diag_id = await persist_diagnostic(
                        db=db,
                        account_id=account_id,
                        system_alias=system.alias,
                        tool_name=f"{system.alias}_{action_name}",
                        action_name=action_name,
                        error_message=result.get("error", ""),
                        diag=diag,
                    )
                    result["diagnostic"] = {
                        "id": diag_id,
                        "category": diag["category"],
                        "summary": diag["diagnosis_summary"],
                        "has_fix": diag["has_fix"],
                        "fix_description": diag.get("fix_description", ""),
                    }
            except Exception as e:
                logger.warning(f"Error diagnosis failed (non-fatal): {e}")

        return result

    except Exception as e:
        logger.error(f"Action execution failed: {e}")
        return {"error": str(e)}


def _inject_project_filter(
    action: Action,
    params: dict[str, Any],
    external_id: str,
    method: str = "GET",
) -> dict[str, Any]:
    """
    Auto-inject project filter for API operations.

    Supports:
    - GET: Query parameter injection
    - POST/PUT/PATCH: Body data injection
    - Path parameter substitution ({project_id}, {project_uuid}, etc.)

    Uses the action's parameters_schema to determine the correct filter field.
    Falls back to common field names if not specified.

    Args:
        action: The Action being executed
        params: Current parameters
        external_id: External project ID to filter by
        method: HTTP method (GET, POST, PUT, etc.)

    Returns:
        Updated parameters with project filter
    """
    # Make a copy to avoid modifying original
    params = dict(params)

    # Check for explicit project filter field in schema
    schema = action.parameters_schema or {}
    project_field = schema.get("_project_filter")
    body_field = schema.get("_project_body_field")  # For POST/PUT body injection

    resource = action.resource
    system_alias = resource.interface.system.alias.lower()

    # Handle path parameter injection for common project param names
    path = action.path or ""
    path_project_params = [
        "project_id",
        "projectId",
        "project_uuid",
        "projectUuid",
        "project_key",
        "projectKey",
        "project",
    ]
    for path_param in path_project_params:
        placeholder = f"{{{path_param}}}"
        if placeholder in path:
            # If not already provided in params, inject it
            if path_param not in params:
                params[path_param] = external_id
                logger.debug(f"Injected path param: {path_param}={external_id}")
            elif params[path_param] != external_id:
                # Conflict: AI provided different ID
                logger.warning(
                    f"Project ID conflict: param '{path_param}'={params[path_param]} "
                    f"vs resolved={external_id}. Using provided value."
                )
            break

    # System-specific handling
    if system_alias == "jira":
        # For Jira, inject into JQL
        existing_jql = params.get("jql", "")
        project_clause = f"project = {external_id}"
        if existing_jql:
            # Check if project already specified
            if "project" not in existing_jql.lower():
                params["jql"] = f"({existing_jql}) AND {project_clause}"
        else:
            params["jql"] = project_clause
        logger.debug(f"Injected Jira project filter: {params.get('jql', '')}")
        return params

    # Handle POST/PUT body injection
    if method in ("POST", "PUT", "PATCH"):
        data = params.get("data", {})
        if isinstance(data, dict):
            # Determine body field name
            if not body_field:
                # Try common body field names
                for field in ["project_id", "projectId", "project_uuid", "projectUuid", "project"]:
                    if field not in data:
                        body_field = field
                        break

            if body_field and body_field not in data:
                # Check for conflict with AI-provided value
                data[body_field] = external_id
                params["data"] = data
                logger.debug(f"Injected body field: data.{body_field}={external_id}")
        return params

    # Handle GET/query parameter injection
    if not project_field:
        # Try common query param names
        for field in ["project", "projectId", "project_id", "project_uuid", "projectKey"]:
            if field not in params:
                project_field = field
                break

    if project_field:
        if project_field not in params:
            params[project_field] = external_id
            logger.debug(f"Injected query param: {project_field}={external_id}")
        elif params[project_field] != external_id:
            # Conflict warning
            logger.warning(
                f"Project ID conflict: param '{project_field}'={params[project_field]} "
                f"vs resolved={external_id}. Using provided value."
            )

    return params


async def _get_auth_headers(
    account_system: AccountSystem, interface: Interface, db: AsyncSession, force_refresh: bool = False
) -> dict[str, str]:
    """Get authentication headers for a system."""
    auth_config = interface.auth or {}
    auth_type = auth_config.get("type", "")

    # DRF token auth (POST username/password -> token)
    if auth_type == "drf_token":
        return await _get_drf_token(account_system, auth_config, db, force_refresh=force_refresh)

    # OAuth with password grant
    if auth_type == "oauth2_password":
        return await _get_oauth_token(account_system, auth_config, db, force_refresh=force_refresh)

    # Bearer type: read prefix from auth config instead of hardcoding
    if auth_type == "bearer":
        prefix = auth_config.get("prefix", "Bearer")
        headers = account_system.get_auth_headers()
        # Override prefix if auth config specifies one and we got an Authorization header
        if "Authorization" in headers and prefix != "Bearer":
            # Replace the prefix part
            token_value = headers["Authorization"].split(" ", 1)[-1] if " " in headers["Authorization"] else headers["Authorization"]
            headers["Authorization"] = f"{prefix} {token_value}"
        return headers

    # Use standard auth from AccountSystem
    return account_system.get_auth_headers()


async def _get_oauth_token(
    account_system: AccountSystem, auth_config: dict, db: AsyncSession, force_refresh: bool = False
) -> dict[str, str]:
    """Get OAuth token using password grant."""
    prefix = auth_config.get("prefix", "Bearer")

    # Check if we have a valid cached token (decrypt from Fernet)
    if not force_refresh:
        decrypted_oauth = account_system._decrypt(account_system.oauth_token)
        if decrypted_oauth and not account_system.is_oauth_expired():
            return {"Authorization": f"{prefix} {decrypted_oauth}"}

    # Need to get a new token
    token_url = auth_config.get("token_url")
    if not token_url:
        logger.error("No token_url in auth config")
        return {}

    # Decrypt credentials (stored encrypted by Django)
    username = account_system.username
    password = account_system._decrypt(account_system.password)

    if not username or not password:
        logger.error("No username/password configured for OAuth")
        return {}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": auth_config.get("grant_type", "password"),
                    "username": username,
                    "password": password,
                },
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(f"OAuth token request failed: {response.status_code}")
                return {}

            data = response.json()

            token_field = auth_config.get("token_field", "access_token")
            expires_field = auth_config.get("expires_field", "expires_in")

            token = data.get(token_field)
            if not token:
                logger.error(f"No {token_field} in OAuth response")
                return {}

            # Cache the token encrypted (must match Django's EncryptedTextField)
            expires_in = data.get(expires_field, 3600)
            encrypted_token = encrypt_value(token)
            from sqlalchemy import text

            await db.execute(
                text("""
                    UPDATE systems_accountsystem
                    SET oauth_token = :token,
                        oauth_expires_at = :expires_at
                    WHERE id = :id
                """),
                {
                    "token": encrypted_token,
                    "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300),
                    "id": account_system.id,
                },
            )
            await db.commit()

            logger.info(f"Obtained OAuth token for {account_system.system.alias}")
            return {"Authorization": f"{prefix} {token}"}

    except Exception as e:
        logger.error(f"OAuth token request failed: {e}")
        return {}


def _detect_token_expiry(token: str, default_ttl: int = 86400) -> int:
    """
    Detect token expiry from JWT exp claim.

    Returns seconds until expiry (with 300s safety margin).
    Falls back to default_ttl if token is not a valid JWT or has no exp claim.
    """
    try:
        # Decode without verification - we just want the exp claim
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp:
            remaining = int(exp) - int(time.time()) - 300  # 300s safety margin
            return max(remaining, 0)
    except (jwt.DecodeError, jwt.InvalidTokenError, Exception):
        pass
    return default_ttl


async def _get_drf_token(
    account_system: AccountSystem, auth_config: dict, db: AsyncSession, force_refresh: bool = False
) -> dict[str, str]:
    """
    Get DRF token by POSTing username/password to token_url.

    Caches the token encrypted in oauth_token field.
    Uses JWT exp claim for expiry detection if available.
    """
    prefix = auth_config.get("prefix", "Token")
    default_ttl = auth_config.get("default_ttl", 86400)

    # Check cached token unless force refresh
    if not force_refresh:
        decrypted_token = account_system._decrypt(account_system.oauth_token)
        if decrypted_token and not account_system.is_oauth_expired():
            return {"Authorization": f"{prefix} {decrypted_token}"}

    # Need to fetch a new token
    token_url = auth_config.get("token_url")
    if not token_url:
        logger.error("No token_url in DRF auth config")
        return {}

    # Get credentials
    username = account_system.username
    password = account_system._decrypt(account_system.password)

    if not username or not password:
        logger.error("No username/password configured for DRF token auth")
        return {}

    try:
        request_format = auth_config.get("request_format", "json")
        token_field = auth_config.get("token_field", "token")

        async with httpx.AsyncClient() as client:
            if request_format == "json":
                response = await client.post(
                    token_url,
                    json={"username": username, "password": password},
                    timeout=30,
                )
            else:
                response = await client.post(
                    token_url,
                    data={"username": username, "password": password},
                    timeout=30,
                )

            if response.status_code != 200:
                logger.error(f"DRF token request failed: {response.status_code} {response.text[:200]}")
                return {}

            data = response.json()
            token = data.get(token_field)
            if not token:
                logger.error(f"No '{token_field}' in DRF token response: {list(data.keys())}")
                return {}

            # Detect expiry from JWT or use default_ttl
            expires_in = _detect_token_expiry(token, default_ttl)

            # Cache token encrypted
            encrypted_token = encrypt_value(token)
            from sqlalchemy import text

            await db.execute(
                text("""
                    UPDATE systems_accountsystem
                    SET oauth_token = :token,
                        oauth_expires_at = :expires_at
                    WHERE id = :id
                """),
                {
                    "token": encrypted_token,
                    "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                    "id": account_system.id,
                },
            )
            await db.commit()

            logger.info(f"Obtained DRF token for {account_system.system.alias} (expires in {expires_in}s)")
            return {"Authorization": f"{prefix} {token}"}

    except Exception as e:
        logger.error(f"DRF token request failed: {e}")
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
            del params[key]

    return result


async def _execute_read(
    url: str,
    method: str,
    params: dict,
    headers: dict,
    action: Action,
    account_id: int = 0,
    source_info: dict | None = None,
) -> dict[str, Any]:
    """Execute a read operation with smart pagination support.

    Pagination modes:
    - No pagination config: plain request, return raw response
    - Paginated (default): fetch one page, return data + pagination metadata
    - Paginated + page=N: fetch specific page
    - Paginated + fetch_all_pages=True: fetch ALL pages, store in cache, return pointer
    """
    pagination_config = action.pagination or {}
    fetch_all = params.pop("fetch_all_pages", False)
    requested_page = params.pop("page", None)

    if fetch_all and pagination_config:
        return await _execute_paginated_read(
            url, method, params, headers, pagination_config, account_id=account_id, source_info=source_info or {}
        )

    if pagination_config:
        return await _execute_single_page_read(url, method, params, headers, pagination_config, requested_page)

    # Non-paginated: plain request
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(method=method, url=url, params=params, headers=headers, timeout=30)
            response.raise_for_status()

            try:
                data = response.json()
            except Exception:
                data = {"text": response.text}

            return {"success": True, "status_code": response.status_code, "data": data}

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": str(e), "status_code": e.response.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_single_page_read(
    url: str, method: str, params: dict, headers: dict, pagination_config: dict, requested_page: int | None = None
) -> dict[str, Any]:
    """Fetch a single page with smart response sizing.

    When called without explicit page param (discovery mode):
    - Returns summary only: item count, column names, 3 sample items
    - Agent can then decide: request specific page, filter, or fetch all

    When called with explicit page=N:
    - Returns full data for that page
    """
    page_param = pagination_config.get("page_param", "page")
    size_param = pagination_config.get("size_param", "size")
    default_size = pagination_config.get("default_size", 100)
    max_size = pagination_config.get("max_size", 100)
    start_page = pagination_config.get("start_page", 0)
    data_field = pagination_config.get("data_field", None)
    last_page_field = pagination_config.get("last_page_field", "last")
    total_pages_field = pagination_config.get("total_pages_field", "totalPages")
    total_elements_field = pagination_config.get("total_elements_field", "totalElements")

    # Discovery mode (no explicit page) vs explicit page request
    is_discovery = requested_page is None
    page = start_page if is_discovery else requested_page
    page_size = min(default_size, max_size)

    page_params = {**params, page_param: page, size_param: page_size}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(method=method, url=url, params=page_params, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()

        # Extract items
        items = _extract_items_from_response(data, data_field)

        # Build pagination metadata
        pagination_info = {
            "page": page,
            "page_size": page_size,
            "items_on_page": len(items),
        }

        if isinstance(data, dict):
            if last_page_field in data:
                pagination_info["has_more"] = not bool(data[last_page_field])
            if total_pages_field in data:
                pagination_info["total_pages"] = data[total_pages_field]
            if total_elements_field in data:
                pagination_info["total_items"] = data[total_elements_field]

        # Estimate total if we have has_more but no total
        if pagination_info.get("has_more") and "total_items" not in pagination_info:
            pagination_info["total_items_hint"] = "more than " + str((page + 1) * page_size)

        if is_discovery:
            # Discovery mode: return summary only, not full data
            columns = list(items[0].keys()) if items and isinstance(items[0], dict) else []
            sample = items[:3]
            result = {
                "success": True,
                "status_code": response.status_code,
                "columns": columns,
                "sample": sample,
                "pagination": pagination_info,
                "hint": (
                    "Use 'page: N' to get a specific page of data, "
                    "or 'fetch_all_pages: true' to fetch all and store as dataset pointer."
                ),
            }
        else:
            # Explicit page request: return full page data
            result = {
                "success": True,
                "status_code": response.status_code,
                "data": items,
                "pagination": pagination_info,
            }

        return result

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": str(e), "status_code": e.response.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _extract_items_from_response(data: Any, data_field: str | None = None) -> list:
    """Extract list items from an API response.

    Handles various response formats:
    - Direct list response
    - Dict with explicit data_field
    - Dict with common field names (content, items, data, etc.)
    - Dict with any list field (fallback)
    """
    if data_field and isinstance(data, dict) and data_field in data:
        return data[data_field]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Try common field names first
        for field in ["content", "items", "data", "results", "records"]:
            if field in data and isinstance(data[field], list):
                return data[field]
        # Fall back to first list field (e.g. Infrakit: 'logpoints', 'machines')
        for key, val in data.items():
            if isinstance(val, list):
                logger.info(f"Auto-detected data field: '{key}' ({len(val)} items)")
                return val
    return []


async def _execute_paginated_read(
    url: str,
    method: str,
    params: dict,
    headers: dict,
    pagination_config: dict,
    account_id: int = 0,
    source_info: dict | None = None,
) -> dict[str, Any]:
    """Execute paginated read, fetching all pages.

    Stores results in dataset cache and returns a summary with pointer
    instead of raw data, to avoid flooding the agent's context.
    """
    page_param = pagination_config.get("page_param", "page")
    size_param = pagination_config.get("size_param", "size")
    default_size = pagination_config.get("default_size", 100)
    max_size = pagination_config.get("max_size", 100)
    start_page = pagination_config.get("start_page", 0)

    data_field = pagination_config.get("data_field", None)
    total_pages_field = pagination_config.get("total_pages_field", "totalPages")
    last_page_field = pagination_config.get("last_page_field", "last")

    max_pages = pagination_config.get("max_pages", 50)
    max_items = pagination_config.get("max_items", 10000)
    max_time_seconds = pagination_config.get("max_time_seconds", 120)

    all_items = []
    current_page = start_page
    start_time = time.time()
    empty_page_count = 0

    try:
        async with httpx.AsyncClient() as client:
            while True:
                if current_page - start_page >= max_pages:
                    break
                if len(all_items) >= max_items:
                    break
                if time.time() - start_time > max_time_seconds:
                    break

                page_params = {**params, page_param: current_page, size_param: min(default_size, max_size)}

                response = await client.request(method=method, url=url, params=page_params, headers=headers, timeout=60)
                response.raise_for_status()
                data = response.json()
                # Extract items from response
                items = _extract_items_from_response(data, data_field)

                if len(items) == 0:
                    empty_page_count += 1
                    if empty_page_count >= 3:
                        break
                else:
                    empty_page_count = 0

                all_items.extend(items)

                # Check if last page
                is_last = False
                if isinstance(data, dict):
                    if last_page_field in data:
                        is_last = bool(data[last_page_field])
                    elif total_pages_field in data:
                        is_last = current_page >= data.get(total_pages_field, 0)
                    elif len(items) < default_size:
                        is_last = True

                if is_last:
                    break

                current_page += 1

        # Store in dataset cache and return summary + pointer
        from .datasets import store_dataset

        summary = store_dataset(
            account_id=account_id,
            items=all_items,
            source_info=source_info or {},
        )
        summary["pages_fetched"] = current_page - start_page + 1
        summary["elapsed_seconds"] = round(time.time() - start_time, 2)

        return {
            "success": True,
            "status_code": 200,
            "dataset": summary,
        }

    except httpx.HTTPStatusError as e:
        result = {
            "success": False,
            "error": str(e),
            "status_code": e.response.status_code,
        }
        if all_items:
            from .datasets import store_dataset

            result["dataset"] = store_dataset(
                account_id=account_id,
                items=all_items,
                source_info={**(source_info or {}), "partial": True},
            )
        return result
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if all_items:
            from .datasets import store_dataset

            result["dataset"] = store_dataset(
                account_id=account_id,
                items=all_items,
                source_info={**(source_info or {}), "partial": True},
            )
        return result


async def _execute_write(url: str, method: str, data: dict, headers: dict) -> dict[str, Any]:
    """Execute a write operation."""
    try:
        content_type = headers.get("Content-Type", "application/json")

        async with httpx.AsyncClient() as client:
            if "json" in content_type:
                response = await client.request(method=method, url=url, json=data, headers=headers, timeout=30)
            else:
                response = await client.request(method=method, url=url, data=data, headers=headers, timeout=30)

            response.raise_for_status()

            try:
                result_data = response.json()
            except Exception:
                result_data = {"text": response.text} if response.text else {}

            return {"success": True, "status_code": response.status_code, "data": result_data}

    except httpx.HTTPStatusError as e:
        error_data = None
        try:
            error_data = e.response.json()
        except Exception:
            error_data = {"text": e.response.text}

        return {"success": False, "error": str(e), "status_code": e.response.status_code, "error_data": error_data}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_graphql(url: str, params: dict, data: dict | None, headers: dict, action: Action) -> dict[str, Any]:
    """
    Execute a GraphQL query or mutation.

    GraphQL always uses POST with a JSON body containing:
    - query: The GraphQL query/mutation string
    - variables: Optional variables object
    - operationName: Optional operation name

    Args:
        url: GraphQL endpoint URL
        params: Tool parameters (may contain query, variables, operation_name)
        data: Optional data dict
        headers: Authentication and other headers
        action: The Action model instance

    Returns:
        Execution result with GraphQL data or errors
    """
    try:
        # Get query from params, data, or action's parameters_schema
        query = None
        variables = {}
        operation_name = None

        # Check params first
        if params:
            query = params.get("query")
            variables = params.get("variables", {})
            operation_name = params.get("operation_name")

        # Fall back to data
        if not query and data:
            query = data.get("query")
            variables = data.get("variables", variables)
            operation_name = data.get("operation_name", operation_name)

        # Fall back to action's parameters_schema (for pre-defined queries)
        if not query and action.parameters_schema:
            query = action.parameters_schema.get("query")
            # Merge default variables with provided ones
            default_vars = action.parameters_schema.get("variables", {})
            variables = {**default_vars, **variables}
            operation_name = operation_name or action.parameters_schema.get("operation_name")

        if not query:
            return {"success": False, "error": "GraphQL query is required"}

        # Build GraphQL request body
        graphql_body = {"query": query}
        if variables:
            graphql_body["variables"] = variables
        if operation_name:
            graphql_body["operationName"] = operation_name

        # Ensure Content-Type is set for JSON
        headers = {**headers, "Content-Type": "application/json"}

        async with httpx.AsyncClient() as client:
            response = await client.post(url=url, json=graphql_body, headers=headers, timeout=60)

            # GraphQL always returns 200, check for errors in response body
            try:
                result = response.json()
            except Exception:
                return {
                    "success": False,
                    "error": "Failed to parse GraphQL response",
                    "status_code": response.status_code,
                    "text": response.text[:1000] if response.text else None,
                }

            # Check for GraphQL errors
            graphql_errors = result.get("errors")
            if graphql_errors:
                # Return both errors and partial data (GraphQL can return both)
                return {
                    "success": False,
                    "errors": graphql_errors,
                    "data": result.get("data"),
                    "status_code": response.status_code,
                }

            # Success
            return {"success": True, "status_code": response.status_code, "data": result.get("data", {})}

    except httpx.HTTPStatusError as e:
        error_data = None
        try:
            error_data = e.response.json()
        except Exception:
            error_data = {"text": e.response.text[:1000] if e.response.text else None}

        return {"success": False, "error": str(e), "status_code": e.response.status_code, "error_data": error_data}
    except Exception as e:
        logger.error(f"GraphQL execution failed: {e}")
        return {"success": False, "error": str(e)}
