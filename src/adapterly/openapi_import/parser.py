"""Parse OpenAPI spec into Integration + Tools JSON."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def parse_openapi_url(url: str) -> dict[str, Any]:
    """Fetch and parse an OpenAPI spec URL into our integration format."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30)
        response.raise_for_status()
        spec = response.json()
    return parse_openapi_spec(spec, source_url=url)


def parse_openapi_spec(spec: dict, source_url: str | None = None) -> dict[str, Any]:
    """Convert OpenAPI 3.x spec to our integration JSON format."""
    info = spec.get("info", {})
    servers = spec.get("servers", [])

    title = info.get("title", "Unknown")
    slug = _slugify(title)
    base_url = servers[0]["url"] if servers else ""

    tools = []
    paths = spec.get("paths", {})

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue

            op_id = operation.get("operationId", "")
            summary = operation.get("summary", "")
            description = operation.get("description", summary)

            tool_slug = _slugify(op_id) if op_id else _slugify(f"{method}_{path}")

            # Build parameters schema
            params_schema = _build_params_schema(operation, method)

            tool_type = "read" if method.lower() in ("get", "head") else "write"

            tools.append({
                "slug": tool_slug,
                "name": summary or op_id or f"{method.upper()} {path}",
                "description": description[:500] if description else "",
                "method": method.upper(),
                "path": path,
                "tool_type": tool_type,
                "parameters_schema": params_schema,
            })

    result = {
        "slug": slug,
        "name": title,
        "description": info.get("description", "")[:500],
        "category": "other",
        "base_url": base_url,
        "auth_config": _detect_auth(spec),
        "tools": tools,
    }

    if source_url:
        result["source_spec_url"] = source_url

    return result


def _build_params_schema(operation: dict, method: str) -> dict:
    """Build JSON Schema from OpenAPI operation parameters."""
    properties = {}
    required = []

    for param in operation.get("parameters", []):
        name = param.get("name", "")
        schema = param.get("schema", {"type": "string"})
        properties[name] = {
            "type": schema.get("type", "string"),
            "description": param.get("description", ""),
        }
        if param.get("required"):
            required.append(name)

    # Request body
    request_body = operation.get("requestBody", {})
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema", {})
        if body_schema:
            properties["data"] = {
                "type": "object",
                "description": "Request body",
            }

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _detect_auth(spec: dict) -> dict:
    """Detect auth configuration from OpenAPI security schemes."""
    components = spec.get("components", {})
    security_schemes = components.get("securitySchemes", {})

    for name, scheme in security_schemes.items():
        scheme_type = scheme.get("type", "")
        if scheme_type == "http":
            sub = scheme.get("scheme", "bearer")
            if sub == "bearer":
                return {
                    "type": "bearer",
                    "fields": [{"name": "token", "label": "Bearer Token", "type": "password", "required": True}],
                }
            elif sub == "basic":
                return {
                    "type": "basic",
                    "fields": [
                        {"name": "username", "label": "Username", "type": "string", "required": True},
                        {"name": "api_key", "label": "Password", "type": "password", "required": True},
                    ],
                }
        elif scheme_type == "apiKey":
            header = scheme.get("name", "X-API-Key")
            return {
                "type": "api_key",
                "header": header,
                "fields": [{"name": "api_key", "label": "API Key", "type": "password", "required": True}],
            }

    return {}


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text[:100]
