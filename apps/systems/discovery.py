"""
Live Discovery Service - Test endpoints and infer schemas automatically.

This service can:
1. Probe endpoints to check if they exist
2. Infer request/response schemas from actual API responses
3. Detect authentication requirements
4. Discover pagination patterns
5. Report progress via callbacks

Usage:
    from apps.systems.discovery import LiveDiscovery

    discovery = LiveDiscovery(
        base_url="https://api.example.com",
        auth_headers={"Authorization": "Bearer xxx"}
    )

    # Discover from hints
    results = await discovery.discover_from_hints([
        {"path": "/users", "methods": ["GET", "POST"]},
        {"path": "/users/{id}", "methods": ["GET", "PUT", "DELETE"]},
    ])

    # Or discover by probing common patterns
    results = await discovery.auto_discover(
        resource_names=["users", "contacts", "deals"]
    )
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DiscoveryStatus(Enum):
    PENDING = "pending"
    TESTING = "testing"
    SUCCESS = "success"
    FAILED = "failed"
    AUTH_REQUIRED = "auth_required"
    SKIPPED = "skipped"


@dataclass
class EndpointResult:
    """Result of testing a single endpoint."""

    method: str
    path: str
    status: DiscoveryStatus
    http_status: int | None = None
    response_time_ms: int | None = None
    request_schema: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=dict)
    sample_response: Any | None = None
    error_message: str | None = None
    requires_auth: bool = False
    pagination: dict[str, Any] | None = None


@dataclass
class DiscoveryProgress:
    """Progress update during discovery."""

    total: int
    completed: int
    current_endpoint: str | None = None
    results: list[EndpointResult] = field(default_factory=list)

    @property
    def percentage(self) -> int:
        return int((self.completed / self.total) * 100) if self.total > 0 else 0


class LiveDiscovery:
    """
    Live API Discovery Service.

    Tests endpoints with real HTTP calls to discover API structure.
    """

    # Common REST patterns to try
    COMMON_PATTERNS = [
        ("list", "GET", "/{resource}"),
        ("get", "GET", "/{resource}/{id}"),
        ("create", "POST", "/{resource}"),
        ("update", "PUT", "/{resource}/{id}"),
        ("patch", "PATCH", "/{resource}/{id}"),
        ("delete", "DELETE", "/{resource}/{id}"),
    ]

    # Common resource names to probe
    COMMON_RESOURCES = [
        "users",
        "accounts",
        "contacts",
        "customers",
        "projects",
        "tasks",
        "issues",
        "tickets",
        "orders",
        "products",
        "items",
        "invoices",
        "deals",
        "leads",
        "opportunities",
        "messages",
        "comments",
        "notes",
        "files",
        "documents",
        "attachments",
    ]

    def __init__(
        self,
        base_url: str,
        auth_headers: dict[str, str] | None = None,
        timeout: int = 30,
        on_progress: Callable[[DiscoveryProgress], None] | None = None,
    ):
        """
        Initialize discovery service.

        Args:
            base_url: API base URL
            auth_headers: Authentication headers
            timeout: Request timeout in seconds
            on_progress: Callback for progress updates
        """
        self.base_url = base_url.rstrip("/")
        self.auth_headers = auth_headers or {}
        self.timeout = timeout
        self.on_progress = on_progress

        self._client: httpx.AsyncClient | None = None
        self._discovered_paths: set[str] = set()

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def discover_from_hints(
        self, hints: list[dict[str, Any]], test_with_sample_data: bool = False
    ) -> list[EndpointResult]:
        """
        Discover endpoints from hints (e.g., from OpenAPI or documentation).

        Args:
            hints: List of endpoint hints with path and methods
            test_with_sample_data: Whether to test POST/PUT with sample data

        Returns:
            List of endpoint results
        """
        results = []
        total = sum(len(h.get("methods", ["GET"])) for h in hints)
        completed = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            self._client = client

            for hint in hints:
                path = hint.get("path", "")
                methods = hint.get("methods", ["GET"])
                _description = hint.get("description", "")

                for method in methods:
                    self._report_progress(total, completed, f"{method} {path}")

                    result = await self._test_endpoint(
                        method=method, path=path, test_body=test_with_sample_data and method in ("POST", "PUT", "PATCH")
                    )
                    results.append(result)
                    completed += 1

                    self._report_progress(total, completed, None, results)

        return results

    async def auto_discover(
        self, resource_names: list[str] | None = None, max_resources: int = 20
    ) -> list[EndpointResult]:
        """
        Automatically discover endpoints by probing common patterns.

        Args:
            resource_names: Resource names to probe (uses common names if not provided)
            max_resources: Maximum resources to probe

        Returns:
            List of discovered endpoints
        """
        resources = resource_names or self.COMMON_RESOURCES[:max_resources]
        results = []
        total = len(resources) * len(self.COMMON_PATTERNS)
        completed = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            self._client = client

            for resource in resources:
                for _action, method, pattern in self.COMMON_PATTERNS:
                    path = pattern.replace("{resource}", resource).replace("{id}", "1")

                    self._report_progress(total, completed, f"{method} {path}")

                    result = await self._test_endpoint(method=method, path=path)

                    # Only include successful discoveries
                    if result.status == DiscoveryStatus.SUCCESS:
                        # Convert back to template path
                        result.path = pattern.replace("{resource}", resource)
                        results.append(result)

                    completed += 1
                    self._report_progress(total, completed, None, results)

        return results

    async def probe_endpoint(
        self, method: str, path: str, body: dict | None = None, query_params: dict | None = None
    ) -> EndpointResult:
        """
        Probe a single endpoint.

        Args:
            method: HTTP method
            path: Endpoint path
            body: Request body for POST/PUT/PATCH
            query_params: Query parameters

        Returns:
            Endpoint result with inferred schemas
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            self._client = client
            return await self._test_endpoint(method=method, path=path, body=body, query_params=query_params)

    async def _test_endpoint(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        query_params: dict | None = None,
        test_body: bool = False,
    ) -> EndpointResult:
        """Test a single endpoint."""
        url = f"{self.base_url}{path}"
        start_time = datetime.now()

        result = EndpointResult(method=method, path=path, status=DiscoveryStatus.TESTING)

        try:
            # Prepare request
            kwargs = {
                "method": method,
                "url": url,
                "headers": {**self.auth_headers, "Accept": "application/json"},
            }

            if query_params:
                kwargs["params"] = query_params

            if body:
                kwargs["json"] = body
            elif test_body and method in ("POST", "PUT", "PATCH"):
                # Generate sample body
                kwargs["json"] = {"test": "discovery"}

            # Make request
            response = await self._client.request(**kwargs)

            # Calculate response time
            result.response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            result.http_status = response.status_code

            # Check status
            if response.status_code == 401:
                result.status = DiscoveryStatus.AUTH_REQUIRED
                result.requires_auth = True
                result.error_message = "Authentication required"

            elif response.status_code == 403:
                result.status = DiscoveryStatus.AUTH_REQUIRED
                result.requires_auth = True
                result.error_message = "Access forbidden"

            elif response.status_code == 404:
                result.status = DiscoveryStatus.FAILED
                result.error_message = "Endpoint not found"

            elif response.status_code >= 400:
                result.status = DiscoveryStatus.FAILED
                result.error_message = f"HTTP {response.status_code}"

            else:
                result.status = DiscoveryStatus.SUCCESS

                # Try to parse response
                try:
                    data = response.json()
                    result.sample_response = self._truncate_sample(data)
                    result.response_schema = self._infer_schema(data)
                    result.pagination = self._detect_pagination(data, response.headers)
                except Exception:
                    result.sample_response = response.text[:500] if response.text else None

        except httpx.TimeoutException:
            result.status = DiscoveryStatus.FAILED
            result.error_message = "Request timeout"

        except httpx.ConnectError as e:
            result.status = DiscoveryStatus.FAILED
            result.error_message = f"Connection error: {str(e)}"

        except Exception as e:
            result.status = DiscoveryStatus.FAILED
            result.error_message = str(e)
            logger.error(f"Error testing {method} {path}: {e}")

        return result

    def _infer_schema(self, data: Any, max_depth: int = 3) -> dict[str, Any]:
        """Infer JSON schema from data."""
        if max_depth <= 0:
            return {"type": "any"}

        if data is None:
            return {"type": "null"}

        if isinstance(data, bool):
            return {"type": "boolean"}

        if isinstance(data, int):
            return {"type": "integer"}

        if isinstance(data, float):
            return {"type": "number"}

        if isinstance(data, str):
            # Try to detect specific string formats
            if re.match(r"^\d{4}-\d{2}-\d{2}", data):
                return {"type": "string", "format": "date-time"}
            if re.match(r"^[a-f0-9-]{36}$", data, re.I):
                return {"type": "string", "format": "uuid"}
            if re.match(r"^[\w.+-]+@[\w.-]+\.\w+$", data):
                return {"type": "string", "format": "email"}
            if re.match(r"^https?://", data):
                return {"type": "string", "format": "uri"}
            return {"type": "string"}

        if isinstance(data, list):
            if not data:
                return {"type": "array", "items": {}}

            # Infer from first item
            item_schema = self._infer_schema(data[0], max_depth - 1)
            return {"type": "array", "items": item_schema}

        if isinstance(data, dict):
            properties = {}
            for key, value in list(data.items())[:20]:  # Limit properties
                properties[key] = self._infer_schema(value, max_depth - 1)

            return {"type": "object", "properties": properties}

        return {"type": "any"}

    def _detect_pagination(self, data: Any, headers: dict) -> dict[str, Any] | None:
        """Detect pagination pattern from response."""
        pagination = {}

        # Check for common pagination patterns in response body
        if isinstance(data, dict):
            # Offset-based
            if "offset" in data or "skip" in data:
                pagination["type"] = "offset"
                pagination["offset_param"] = "offset" if "offset" in data else "skip"

            # Page-based
            if "page" in data or "current_page" in data:
                pagination["type"] = "page"
                pagination["page_param"] = "page"
                if "total_pages" in data:
                    pagination["total_pages_field"] = "total_pages"
                if "per_page" in data:
                    pagination["per_page_param"] = "per_page"

            # Cursor-based
            if "cursor" in data or "next_cursor" in data:
                pagination["type"] = "cursor"
                pagination["cursor_field"] = "next_cursor" if "next_cursor" in data else "cursor"

            # Total count
            for field in ["total", "total_count", "count", "total_items"]:
                if field in data:
                    pagination["total_field"] = field
                    break

            # Next/prev links
            if "next" in data or "next_url" in data:
                pagination["next_field"] = "next" if "next" in data else "next_url"

        # Check headers
        if "Link" in headers:
            pagination["type"] = "link_header"
            pagination["link_header"] = True

        if "X-Total-Count" in headers:
            pagination["total_header"] = "X-Total-Count"

        return pagination if pagination else None

    def _truncate_sample(self, data: Any, max_items: int = 3) -> Any:
        """Truncate sample data for storage."""
        if isinstance(data, list):
            return data[:max_items]
        if isinstance(data, dict):
            return {k: self._truncate_sample(v, max_items) for k, v in list(data.items())[:20]}
        if isinstance(data, str) and len(data) > 200:
            return data[:200] + "..."
        return data

    def _report_progress(self, total: int, completed: int, current: str | None, results: list[EndpointResult] = None):
        """Report progress via callback."""
        if self.on_progress:
            progress = DiscoveryProgress(
                total=total, completed=completed, current_endpoint=current, results=results or []
            )
            self.on_progress(progress)


class SchemaInferer:
    """
    Advanced schema inference from multiple samples.

    Builds more accurate schemas by analyzing multiple API responses.
    """

    def __init__(self):
        self.samples: list[Any] = []

    def add_sample(self, data: Any):
        """Add a sample response."""
        self.samples.append(data)

    def infer_schema(self) -> dict[str, Any]:
        """Infer schema from all collected samples."""
        if not self.samples:
            return {}

        # Start with first sample
        schema = self._infer_single(self.samples[0])

        # Merge with other samples to find optional fields
        for sample in self.samples[1:]:
            sample_schema = self._infer_single(sample)
            schema = self._merge_schemas(schema, sample_schema)

        return schema

    def _infer_single(self, data: Any) -> dict[str, Any]:
        """Infer schema from single sample."""
        if data is None:
            return {"type": "null", "nullable": True}

        if isinstance(data, bool):
            return {"type": "boolean"}

        if isinstance(data, int):
            return {"type": "integer"}

        if isinstance(data, float):
            return {"type": "number"}

        if isinstance(data, str):
            schema = {"type": "string"}

            # Detect formats
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data):
                schema["format"] = "date-time"
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", data):
                schema["format"] = "date"
            elif re.match(r"^[a-f0-9-]{36}$", data, re.I):
                schema["format"] = "uuid"
            elif re.match(r"^[\w.+-]+@[\w.-]+\.\w+$", data):
                schema["format"] = "email"
            elif re.match(r"^https?://", data):
                schema["format"] = "uri"

            return schema

        if isinstance(data, list):
            if not data:
                return {"type": "array", "items": {}}

            # Infer from all items and merge
            item_schemas = [self._infer_single(item) for item in data[:10]]
            merged_item = item_schemas[0]
            for s in item_schemas[1:]:
                merged_item = self._merge_schemas(merged_item, s)

            return {"type": "array", "items": merged_item}

        if isinstance(data, dict):
            properties = {}
            required = []

            for key, value in data.items():
                properties[key] = self._infer_single(value)
                required.append(key)

            return {"type": "object", "properties": properties, "required": required}

        return {"type": "any"}

    def _merge_schemas(self, schema1: dict, schema2: dict) -> dict:
        """Merge two schemas, finding common structure."""
        if schema1.get("type") != schema2.get("type"):
            # Different types - use anyOf
            return {"anyOf": [schema1, schema2]}

        if schema1.get("type") == "object":
            # Merge object properties
            props1 = schema1.get("properties", {})
            props2 = schema2.get("properties", {})
            req1 = set(schema1.get("required", []))
            req2 = set(schema2.get("required", []))

            merged_props = {}
            all_keys = set(props1.keys()) | set(props2.keys())

            for key in all_keys:
                if key in props1 and key in props2:
                    merged_props[key] = self._merge_schemas(props1[key], props2[key])
                elif key in props1:
                    merged_props[key] = props1[key]
                else:
                    merged_props[key] = props2[key]

            # Required = intersection (present in all samples)
            required = list(req1 & req2)

            return {"type": "object", "properties": merged_props, "required": required if required else None}

        if schema1.get("type") == "array":
            # Merge array item schemas
            items1 = schema1.get("items", {})
            items2 = schema2.get("items", {})
            return {"type": "array", "items": self._merge_schemas(items1, items2)}

        # Same primitive type - return first
        return schema1
