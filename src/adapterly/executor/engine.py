"""HTTP execution engine – executes tool calls against external APIs."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import decrypt_value, encrypt_value
from ..models.connection import Connection
from ..models.integration import Integration, Tool

logger = logging.getLogger(__name__)

# Shared httpx client
_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=120),
        )
    return _shared_client


async def execute_tool(
    tool: Tool,
    integration: Integration,
    connection: Connection,
    params: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Execute a tool call against the external API."""
    try:
        method = tool.method.upper()

        # Resolve base URL
        base_url = connection.base_url_override or integration.base_url
        if not base_url:
            return {"error": f"No base URL configured for {integration.slug}"}

        # Resolve variables in base_url (e.g. {domain})
        base_url = _resolve_variables(base_url, integration.variables, connection.credentials)

        # Build auth headers
        auth_headers = _get_auth_headers(integration, connection)
        if not auth_headers and integration.auth_config.get("type"):
            return {"error": f"No credentials configured for {integration.slug}"}

        # Substitute path params
        original_params = dict(params)
        path = _substitute_path_params(tool.path, params)
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}" if path else base_url

        # Inject external_id if configured
        if connection.external_id:
            params = _inject_external_id(tool, params, connection.external_id, method)

        data = params.pop("data", None)
        headers = {**(tool.headers or {}), **auth_headers}

        # Execute based on method
        if method in ("GET", "HEAD", "OPTIONS"):
            result = await _execute_read(
                url=url, method=method, params=params, headers=headers, tool=tool,
            )
        else:
            result = await _execute_write(
                url=url, method=method, data=data or params, headers=headers,
            )

        return result

    except Exception as e:
        logger.error(f"Tool execution failed: {e}", exc_info=True)
        return {"error": str(e)}


def _resolve_variables(base_url: str, variables: dict, credentials: dict) -> str:
    """Replace {variable} placeholders in base_url using variable definitions."""
    for var_name, var_config in (variables or {}).items():
        placeholder = f"{{{var_name}}}"
        if placeholder not in base_url:
            continue

        source = var_config.get("source", "credential")
        field = var_config.get("field", var_name)

        if source == "credential":
            value = credentials.get(field, "")
            if value:
                value = decrypt_value(value)
        else:
            value = var_config.get("default", "")

        base_url = base_url.replace(placeholder, value or "")

    return base_url


def _get_auth_headers(integration: Integration, connection: Connection) -> dict[str, str]:
    """Build auth headers from connection credentials."""
    auth_config = integration.auth_config or {}
    auth_type = auth_config.get("type", "")
    creds = connection.credentials or {}

    if auth_type == "bearer":
        token = creds.get("token", "")
        if token:
            token = decrypt_value(token)
            prefix = auth_config.get("prefix", "Bearer")
            return {"Authorization": f"{prefix} {token}"}

    elif auth_type == "basic":
        username = creds.get("username", "")
        api_key = creds.get("api_key", "")
        if username:
            username = decrypt_value(username)
        if api_key:
            api_key = decrypt_value(api_key)
        if username and api_key:
            import base64
            encoded = base64.b64encode(f"{username}:{api_key}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

    elif auth_type == "api_key":
        key_value = creds.get("api_key", "")
        if key_value:
            key_value = decrypt_value(key_value)
            header_name = auth_config.get("header", "X-API-Key")
            return {header_name: key_value}

    elif auth_type == "custom":
        # Custom headers from custom_settings
        custom = connection.custom_settings or {}
        headers = {}
        for field_def in auth_config.get("fields", []):
            name = field_def["name"]
            value = creds.get(name, "")
            if value:
                value = decrypt_value(value)
                header = custom.get(f"{name}_header", field_def.get("header"))
                if header:
                    headers[header] = value
        return headers

    return {}


def _substitute_path_params(path: str, params: dict) -> str:
    if not path:
        return ""
    result = path
    for key, value in list(params.items()):
        placeholder = f"{{{key}}}"
        if placeholder in result:
            result = result.replace(placeholder, str(value))
            del params[key]
    return result


def _inject_external_id(
    tool: Tool,
    params: dict[str, Any],
    external_id: str,
    method: str,
) -> dict[str, Any]:
    """Auto-inject project/external ID filter."""
    params = dict(params)
    schema = tool.parameters_schema or {}
    project_field = schema.get("_project_filter")

    path = tool.path or ""
    for path_param in ["project_id", "projectId", "project_uuid", "projectUuid", "project"]:
        if f"{{{path_param}}}" in path and path_param not in params:
            params[path_param] = external_id
            return params

    if method in ("POST", "PUT", "PATCH"):
        data = params.get("data", {})
        if isinstance(data, dict):
            for field in ["project_id", "projectId", "project_uuid", "project"]:
                if field not in data:
                    data[field] = external_id
                    params["data"] = data
                    break
        return params

    if not project_field:
        for field in ["project", "projectId", "project_id", "project_uuid"]:
            if field not in params:
                project_field = field
                break

    if project_field and project_field not in params:
        params[project_field] = external_id

    return params


# ---------------------------------------------------------------------------
# HTTP execution
# ---------------------------------------------------------------------------


async def _execute_read(
    url: str,
    method: str,
    params: dict,
    headers: dict,
    tool: Tool,
) -> dict[str, Any]:
    """Execute a read operation with pagination support."""
    pagination_config = tool.pagination or {}
    fetch_all = params.pop("fetch_all_pages", False)
    requested_page = params.pop("page", None)

    if fetch_all and pagination_config:
        return await _execute_paginated_read(url, method, params, headers, pagination_config)

    if pagination_config:
        return await _execute_single_page_read(url, method, params, headers, pagination_config, requested_page)

    # Simple non-paginated read
    try:
        client = _get_shared_client()
        response = await client.request(method=method, url=url, params=params, headers=headers, timeout=30)
        response.raise_for_status()

        try:
            data = response.json()
        except Exception:
            data = {"text": response.text}

        return {"success": True, "status_code": response.status_code, "data": data}

    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except Exception as e:
        return {"error": str(e)}


async def _execute_single_page_read(
    url: str, method: str, params: dict, headers: dict,
    pagination_config: dict, requested_page: int | None = None,
) -> dict[str, Any]:
    page_param = pagination_config.get("page_param", "page")
    size_param = pagination_config.get("size_param", "size")
    default_size = pagination_config.get("default_size", 100)
    max_size = pagination_config.get("max_size", 100)
    start_page = pagination_config.get("start_page", 0)
    data_field = pagination_config.get("data_field")
    total_field = pagination_config.get("total_field", "total")

    is_discovery = requested_page is None
    page = start_page if is_discovery else requested_page
    page_size = min(default_size, max_size)

    page_params = {**params, page_param: page, size_param: page_size}

    try:
        client = _get_shared_client()
        response = await client.request(method=method, url=url, params=page_params, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()

        items = _extract_items(data, data_field)

        pagination_info = {
            "page": page,
            "page_size": page_size,
            "items_on_page": len(items),
        }

        if isinstance(data, dict) and total_field in data:
            pagination_info["total_items"] = data[total_field]

        if is_discovery:
            columns = list(items[0].keys()) if items and isinstance(items[0], dict) else []
            return {
                "success": True,
                "status_code": response.status_code,
                "count": pagination_info.get("total_items", len(items)),
                "columns": columns,
                "sample": items[:3],
                "pagination": pagination_info,
                "hint": "Use 'page: N' for full page data, 'fetch_all_pages: true' to store all as dataset pointer.",
            }
        else:
            return {
                "success": True,
                "status_code": response.status_code,
                "data": items,
                "pagination": pagination_info,
            }

    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except Exception as e:
        return {"error": str(e)}


async def _execute_paginated_read(
    url: str, method: str, params: dict, headers: dict, pagination_config: dict,
) -> dict[str, Any]:
    page_param = pagination_config.get("page_param", "page")
    size_param = pagination_config.get("size_param", "size")
    max_size = pagination_config.get("max_size", 100)
    start_page = pagination_config.get("start_page", 0)
    data_field = pagination_config.get("data_field")
    total_field = pagination_config.get("total_field", "total")
    max_pages = pagination_config.get("max_pages", 50)
    max_items = pagination_config.get("max_items", 10000)
    page_delay = pagination_config.get("page_delay", 0.2)

    all_items = []
    current_page = start_page
    start_time = time.time()

    try:
        client = _get_shared_client()
        while True:
            if current_page - start_page >= max_pages:
                break
            if len(all_items) >= max_items:
                break
            if time.time() - start_time > 120:
                break

            if current_page > start_page and page_delay > 0:
                await asyncio.sleep(page_delay)

            page_params = {**params, page_param: current_page, size_param: max_size}
            response = await client.request(method=method, url=url, params=page_params, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            items = _extract_items(data, data_field)

            if not items:
                break

            all_items.extend(items)

            if len(items) < max_size:
                break

            current_page += 1

        return {
            "success": True,
            "status_code": 200,
            "dataset": {
                "total_items": len(all_items),
                "pages_fetched": current_page - start_page + 1,
                "elapsed_seconds": round(time.time() - start_time, 2),
                "data": all_items,
            },
        }

    except httpx.HTTPStatusError as e:
        result = _http_error(e)
        if all_items:
            result["partial_items_count"] = len(all_items)
        return result
    except Exception as e:
        result = {"error": str(e)}
        if all_items:
            result["partial_items_count"] = len(all_items)
        return result


async def _execute_write(url: str, method: str, data: dict, headers: dict) -> dict[str, Any]:
    try:
        client = _get_shared_client()
        content_type = headers.get("Content-Type", "application/json")

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
        return _http_error(e)
    except Exception as e:
        return {"error": str(e)}


def _extract_items(data: Any, data_field: str | None = None) -> list:
    if data_field and isinstance(data, dict) and data_field in data:
        return data[data_field]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for field in ["content", "items", "data", "results", "records"]:
            if field in data and isinstance(data[field], list):
                return data[field]
    return []


def _http_error(e: httpx.HTTPStatusError) -> dict[str, Any]:
    error_data = None
    try:
        error_data = e.response.json()
    except Exception:
        error_data = {"text": e.response.text[:1000] if e.response.text else None}
    return {"error": str(e), "status_code": e.response.status_code, "error_data": error_data}
