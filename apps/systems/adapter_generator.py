"""
Adapter Generator - Automatically create System adapters from various sources.

Supported sources:
1. OpenAPI/Swagger specification (JSON/YAML)
2. AI analysis of API documentation (web pages, text)
3. HAR file analysis (browser HTTP traffic)

Usage:
    from apps.systems.adapter_generator import AdapterGenerator

    # From OpenAPI spec
    generator = AdapterGenerator(account_id=1)
    system = generator.from_openapi(spec_url="https://api.example.com/openapi.json")

    # From documentation URL
    system = generator.from_documentation(
        url="https://docs.example.com/api",
        system_name="Example API"
    )

    # From HAR file
    system = generator.from_har(har_file_path="/path/to/traffic.har")
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import requests
import yaml

logger = logging.getLogger(__name__)


@dataclass
class GeneratedAction:
    """Represents a generated API action."""

    name: str
    alias: str
    description: str
    method: str
    path: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class GeneratedResource:
    """Represents a generated API resource."""

    name: str
    alias: str
    description: str
    actions: list[GeneratedAction] = field(default_factory=list)


@dataclass
class GeneratedInterface:
    """Represents a generated API interface."""

    name: str
    alias: str
    type: str  # API or XHR
    base_url: str
    auth: dict[str, Any] = field(default_factory=dict)
    resources: list[GeneratedResource] = field(default_factory=list)


@dataclass
class GeneratedSystem:
    """Represents a generated system configuration."""

    name: str
    alias: str
    display_name: str
    description: str
    system_type: str
    website_url: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    interfaces: list[GeneratedInterface] = field(default_factory=list)


class AdapterGenerator:
    """
    Generate System adapters from various sources.
    """

    def __init__(self, account_id: int | None = None):
        self.account_id = account_id

    # =========================================================================
    # OpenAPI / Swagger Parser
    # =========================================================================

    def from_openapi(
        self,
        spec: dict | None = None,
        spec_url: str | None = None,
        spec_file: str | None = None,
        system_name: str | None = None,
        system_alias: str | None = None,
    ) -> GeneratedSystem:
        """
        Generate System from OpenAPI/Swagger specification.

        Args:
            spec: OpenAPI spec as dict
            spec_url: URL to fetch spec from
            spec_file: Path to spec file (JSON or YAML)
            system_name: Override system name
            system_alias: Override system alias

        Returns:
            GeneratedSystem with interfaces, resources, and actions
        """
        # Load spec
        if spec is None:
            if spec_url:
                spec = self._fetch_openapi_spec(spec_url)
            elif spec_file:
                spec = self._load_openapi_file(spec_file)
            else:
                raise ValueError("Must provide spec, spec_url, or spec_file")

        # Detect version
        is_openapi3 = spec.get("openapi", "").startswith("3.")
        is_swagger2 = spec.get("swagger", "").startswith("2.")

        if not is_openapi3 and not is_swagger2:
            raise ValueError("Unsupported spec format. Must be OpenAPI 3.x or Swagger 2.x")

        # Extract metadata
        info = spec.get("info", {})
        name = system_name or info.get("title", "Unknown API")
        alias = system_alias or self._slugify(name)

        # Get base URL
        if is_openapi3:
            servers = spec.get("servers", [])
            base_url = servers[0].get("url", "") if servers else ""
        else:
            # Swagger 2.0
            host = spec.get("host", "")
            base_path = spec.get("basePath", "")
            schemes = spec.get("schemes", ["https"])
            base_url = f"{schemes[0]}://{host}{base_path}"

        # Parse paths into resources and actions
        resources = self._parse_openapi_paths(spec, is_openapi3)

        # Detect auth type
        auth = self._parse_openapi_security(spec, is_openapi3)

        # Build interface
        interface = GeneratedInterface(
            name="api", alias="api", type="API", base_url=base_url, auth=auth, resources=resources
        )

        # Build system
        return GeneratedSystem(
            name=name,
            alias=alias,
            display_name=name,
            description=info.get("description", ""),
            system_type=self._guess_system_type(name, spec),
            website_url=info.get("termsOfService", ""),
            variables={"api_version": info.get("version", "1.0")},
            interfaces=[interface],
        )

    def _fetch_openapi_spec(self, url: str) -> dict:
        """Fetch OpenAPI spec from URL."""
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "yaml" in content_type or url.endswith((".yaml", ".yml")):
            return yaml.safe_load(response.text)
        return response.json()

    def _load_openapi_file(self, path: str) -> dict:
        """Load OpenAPI spec from file."""
        with open(path) as f:
            content = f.read()
            if path.endswith((".yaml", ".yml")):
                return yaml.safe_load(content)
            return json.loads(content)

    def _parse_openapi_paths(self, spec: dict, is_openapi3: bool) -> list[GeneratedResource]:
        """Parse OpenAPI paths into resources and actions."""
        paths = spec.get("paths", {})
        resources_map: dict[str, GeneratedResource] = {}

        for path, path_item in paths.items():
            # Extract resource name from path (e.g., /users/{id} -> users)
            resource_name = self._extract_resource_name(path)

            if resource_name not in resources_map:
                resources_map[resource_name] = GeneratedResource(
                    name=resource_name,
                    alias=self._slugify(resource_name),
                    description=f"Operations on {resource_name}",
                    actions=[],
                )

            resource = resources_map[resource_name]

            # Parse each HTTP method
            for method in ["get", "post", "put", "patch", "delete"]:
                if method not in path_item:
                    continue

                operation = path_item[method]
                action = self._parse_openapi_operation(path, method, operation, spec, is_openapi3)
                resource.actions.append(action)

        return list(resources_map.values())

    def _parse_openapi_operation(
        self, path: str, method: str, operation: dict, spec: dict, is_openapi3: bool
    ) -> GeneratedAction:
        """Parse a single OpenAPI operation into an action."""
        # Generate action name
        operation_id = operation.get("operationId", "")
        if operation_id:
            action_name = operation_id
        else:
            # Generate from method + path
            action_name = self._generate_action_name(method, path)

        # Build parameters schema
        params_schema = self._build_params_schema(operation, spec, is_openapi3)

        # Build output schema
        output_schema = self._build_output_schema(operation, spec, is_openapi3)

        return GeneratedAction(
            name=action_name,
            alias=self._slugify(action_name),
            description=operation.get("summary", "") or operation.get("description", ""),
            method=method.upper(),
            path=path,
            parameters_schema=params_schema,
            output_schema=output_schema,
        )

    def _build_params_schema(self, operation: dict, spec: dict, is_openapi3: bool) -> dict:
        """Build JSON Schema for operation parameters."""
        properties = {}
        required = []

        # Path/query/header parameters
        for param in operation.get("parameters", []):
            # Resolve $ref
            if "$ref" in param:
                param = self._resolve_ref(param["$ref"], spec)

            name = param.get("name", "")
            param_in = param.get("in", "")

            if param_in in ("path", "query", "header"):
                prop = {"type": "string", "description": param.get("description", "")}

                if is_openapi3:
                    schema = param.get("schema", {})
                    prop["type"] = schema.get("type", "string")
                else:
                    prop["type"] = param.get("type", "string")

                properties[name] = prop

                if param.get("required", False):
                    required.append(name)

        # Request body (OpenAPI 3)
        if is_openapi3 and "requestBody" in operation:
            body = operation["requestBody"]
            content = body.get("content", {})
            json_content = content.get("application/json", {})
            body_schema = json_content.get("schema", {})

            if body_schema:
                properties["body"] = {
                    "type": "object",
                    "description": "Request body",
                    "properties": self._extract_schema_properties(body_schema, spec),
                }
                if body.get("required", False):
                    required.append("body")

        # Request body (Swagger 2)
        else:
            for param in operation.get("parameters", []):
                if param.get("in") == "body":
                    schema = param.get("schema", {})
                    properties["body"] = {
                        "type": "object",
                        "description": param.get("description", "Request body"),
                        "properties": self._extract_schema_properties(schema, spec),
                    }
                    if param.get("required", False):
                        required.append("body")

        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required

        return schema

    def _build_output_schema(self, operation: dict, spec: dict, is_openapi3: bool) -> dict:
        """Build JSON Schema for operation response."""
        responses = operation.get("responses", {})

        # Look for 200/201 response
        success_response = responses.get("200") or responses.get("201") or responses.get("default")

        if not success_response:
            return {}

        if is_openapi3:
            content = success_response.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema", {})
        else:
            schema = success_response.get("schema", {})

        return self._extract_schema_properties(schema, spec)

    def _extract_schema_properties(self, schema: dict, spec: dict) -> dict:
        """Extract properties from a schema, resolving refs."""
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], spec)

        if schema.get("type") == "array":
            items = schema.get("items", {})
            if "$ref" in items:
                items = self._resolve_ref(items["$ref"], spec)
            return {"type": "array", "items": items.get("properties", {})}

        return schema.get("properties", {})

    def _resolve_ref(self, ref: str, spec: dict) -> dict:
        """Resolve a JSON Schema $ref."""
        if not ref.startswith("#/"):
            return {}

        parts = ref[2:].split("/")
        current = spec

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}

        return current if isinstance(current, dict) else {}

    def _parse_openapi_security(self, spec: dict, is_openapi3: bool) -> dict:
        """Parse security definitions."""
        auth = {}

        if is_openapi3:
            security_schemes = spec.get("components", {}).get("securitySchemes", {})
        else:
            security_schemes = spec.get("securityDefinitions", {})

        for _name, scheme in security_schemes.items():
            scheme_type = scheme.get("type", "")

            if scheme_type == "apiKey":
                auth["type"] = "api_key"
                auth["header"] = scheme.get("name", "X-API-Key")
                auth["in"] = scheme.get("in", "header")
            elif scheme_type in ("oauth2", "OAuth2"):
                auth["type"] = "oauth2"
                if is_openapi3:
                    flows = scheme.get("flows", {})
                    if "authorizationCode" in flows:
                        auth["authorization_url"] = flows["authorizationCode"].get("authorizationUrl")
                        auth["token_url"] = flows["authorizationCode"].get("tokenUrl")
                else:
                    auth["authorization_url"] = scheme.get("authorizationUrl")
                    auth["token_url"] = scheme.get("tokenUrl")
            elif scheme_type == "http":
                auth["type"] = scheme.get("scheme", "bearer")
            elif scheme_type == "basic":
                auth["type"] = "basic"

        return auth

    # =========================================================================
    # AI-based Documentation Analyzer
    # =========================================================================

    def from_documentation(
        self,
        url: str | None = None,
        text: str | None = None,
        system_name: str = "Unknown API",
        system_alias: str | None = None,
        base_url: str | None = None,
    ) -> GeneratedSystem:
        """
        Generate System by analyzing API documentation with AI.

        Args:
            url: URL to API documentation
            text: Raw documentation text
            system_name: Name for the system
            system_alias: Alias for the system
            base_url: Base URL for API (if known)

        Returns:
            GeneratedSystem with extracted endpoints
        """
        # Fetch documentation if URL provided
        if url and not text:
            text = self._fetch_documentation(url)

        if not text:
            raise ValueError("Must provide url or text")

        # Use AI to analyze documentation
        analysis = self._analyze_documentation_with_ai(text, system_name, base_url)

        # Build system from analysis
        alias = system_alias or self._slugify(system_name)

        return GeneratedSystem(
            name=system_name,
            alias=alias,
            display_name=system_name,
            description=analysis.get("description", ""),
            system_type=analysis.get("system_type", "other"),
            website_url=url or "",
            variables=analysis.get("variables", {}),
            interfaces=self._build_interfaces_from_analysis(analysis, base_url),
        )

    def _fetch_documentation(self, url: str) -> str:
        """Fetch documentation from URL."""
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Try to extract text from HTML
        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            return self._extract_text_from_html(response.text)

        return response.text

    def _extract_text_from_html(self, html: str) -> str:
        """Extract text from HTML, focusing on API-relevant content."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Remove scripts and styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            # Look for API-relevant sections
            main_content = soup.find("main") or soup.find("article") or soup.find("body")

            if main_content:
                return main_content.get_text(separator="\n", strip=True)

            return soup.get_text(separator="\n", strip=True)
        except ImportError:
            # Fallback: simple regex-based extraction
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            return " ".join(text.split())

    def _analyze_documentation_with_ai(self, text: str, system_name: str, base_url: str | None) -> dict:
        """Use AI to analyze documentation and extract API structure."""
        import openai
        from django.conf import settings

        # Truncate text if too long
        max_chars = 15000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"

        prompt = f"""Analyze this API documentation and extract the API structure.

API Name: {system_name}
Base URL (if known): {base_url or "Unknown"}

Documentation:
{text}

Extract and return a JSON object with:
{{
    "description": "Brief description of the API",
    "system_type": "project_management|communication|storage|monitoring|other",
    "base_url": "Detected base URL or null",
    "auth_type": "api_key|oauth2|bearer|basic|none",
    "auth_header": "Header name for API key if applicable",
    "resources": [
        {{
            "name": "resource_name",
            "description": "What this resource represents",
            "actions": [
                {{
                    "name": "action_name",
                    "method": "GET|POST|PUT|DELETE",
                    "path": "/path/to/endpoint",
                    "description": "What this action does",
                    "parameters": [
                        {{"name": "param", "type": "string|integer|boolean", "required": true, "description": "..."}}
                    ]
                }}
            ]
        }}
    ]
}}

Only include endpoints you find in the documentation. Return valid JSON only."""

        try:
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an API documentation analyzer. Extract API structure from documentation and return JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            return result

        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {"description": f"API: {system_name}", "system_type": "other", "resources": []}

    def _build_interfaces_from_analysis(self, analysis: dict, base_url: str | None) -> list[GeneratedInterface]:
        """Build interfaces from AI analysis result."""
        resources = []

        for res_data in analysis.get("resources", []):
            actions = []

            for act_data in res_data.get("actions", []):
                # Build parameters schema
                params_schema = {"type": "object", "properties": {}, "required": []}

                for param in act_data.get("parameters", []):
                    params_schema["properties"][param["name"]] = {
                        "type": param.get("type", "string"),
                        "description": param.get("description", ""),
                    }
                    if param.get("required", False):
                        params_schema["required"].append(param["name"])

                actions.append(
                    GeneratedAction(
                        name=act_data.get("name", "unknown"),
                        alias=self._slugify(act_data.get("name", "unknown")),
                        description=act_data.get("description", ""),
                        method=act_data.get("method", "GET"),
                        path=act_data.get("path", "/"),
                        parameters_schema=params_schema,
                    )
                )

            resources.append(
                GeneratedResource(
                    name=res_data.get("name", "unknown"),
                    alias=self._slugify(res_data.get("name", "unknown")),
                    description=res_data.get("description", ""),
                    actions=actions,
                )
            )

        # Build auth config
        auth = {}
        if analysis.get("auth_type"):
            auth["type"] = analysis["auth_type"]
            if analysis.get("auth_header"):
                auth["header"] = analysis["auth_header"]

        interface = GeneratedInterface(
            name="api",
            alias="api",
            type="API",
            base_url=analysis.get("base_url") or base_url or "",
            auth=auth,
            resources=resources,
        )

        return [interface]

    # =========================================================================
    # HAR File Analyzer
    # =========================================================================

    def from_har(
        self,
        har_file: str | None = None,
        har_data: dict | None = None,
        system_name: str = "Unknown API",
        system_alias: str | None = None,
        filter_domain: str | None = None,
    ) -> GeneratedSystem:
        """
        Generate System by analyzing HAR (HTTP Archive) file.

        Args:
            har_file: Path to HAR file
            har_data: HAR data as dict
            system_name: Name for the system
            system_alias: Alias for the system
            filter_domain: Only include requests to this domain

        Returns:
            GeneratedSystem with detected endpoints
        """
        # Load HAR
        if har_data is None:
            if har_file:
                with open(har_file) as f:
                    har_data = json.load(f)
            else:
                raise ValueError("Must provide har_file or har_data")

        # Extract requests
        entries = har_data.get("log", {}).get("entries", [])

        # Group by domain and path
        endpoints: dict[str, dict] = {}
        base_url = None

        for entry in entries:
            request = entry.get("request", {})
            response = entry.get("response", {})

            url = request.get("url", "")
            method = request.get("method", "GET")

            # Parse URL
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(url)

            # Filter by domain if specified
            if filter_domain and filter_domain not in parsed.netloc:
                continue

            # Skip non-API requests
            if self._is_static_resource(parsed.path):
                continue

            # Detect base URL
            if base_url is None:
                base_url = f"{parsed.scheme}://{parsed.netloc}"

            # Normalize path (replace IDs with {id})
            normalized_path = self._normalize_path(parsed.path)

            # Create endpoint key
            endpoint_key = f"{method}:{normalized_path}"

            if endpoint_key not in endpoints:
                endpoints[endpoint_key] = {
                    "method": method,
                    "path": normalized_path,
                    "query_params": set(),
                    "request_headers": set(),
                    "request_body_keys": set(),
                    "response_content_type": None,
                    "examples": [],
                }

            ep = endpoints[endpoint_key]

            # Collect query parameters
            for key in parse_qs(parsed.query).keys():
                ep["query_params"].add(key)

            # Collect relevant headers
            for header in request.get("headers", []):
                name = header.get("name", "").lower()
                if name in ("authorization", "x-api-key", "content-type"):
                    ep["request_headers"].add(header.get("name"))

            # Collect request body keys
            post_data = request.get("postData", {})
            if post_data.get("mimeType", "").startswith("application/json"):
                try:
                    body = json.loads(post_data.get("text", "{}"))
                    if isinstance(body, dict):
                        ep["request_body_keys"].update(body.keys())
                except json.JSONDecodeError:
                    pass

            # Detect response content type
            if not ep["response_content_type"]:
                content = response.get("content", {})
                ep["response_content_type"] = content.get("mimeType", "")

        # Build resources and actions
        resources = self._build_resources_from_har(endpoints)

        # Build interface
        alias = system_alias or self._slugify(system_name)

        interface = GeneratedInterface(
            name="api", alias="api", type="API", base_url=base_url or "", resources=resources
        )

        return GeneratedSystem(
            name=system_name,
            alias=alias,
            display_name=system_name,
            description=f"Generated from HAR analysis ({len(endpoints)} endpoints)",
            system_type="other",
            interfaces=[interface],
        )

    def _is_static_resource(self, path: str) -> bool:
        """Check if path is a static resource."""
        static_extensions = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf")
        return path.lower().endswith(static_extensions)

    def _normalize_path(self, path: str) -> str:
        """Normalize path by replacing IDs with placeholders."""
        # Replace UUIDs
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "{id}", path, flags=re.IGNORECASE
        )
        # Replace numeric IDs
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
        return path

    def _build_resources_from_har(self, endpoints: dict) -> list[GeneratedResource]:
        """Build resources from HAR endpoints."""
        resources_map: dict[str, GeneratedResource] = {}

        for _key, ep in endpoints.items():
            path = ep["path"]
            resource_name = self._extract_resource_name(path)

            if resource_name not in resources_map:
                resources_map[resource_name] = GeneratedResource(
                    name=resource_name,
                    alias=self._slugify(resource_name),
                    description=f"Operations on {resource_name}",
                    actions=[],
                )

            # Build parameters schema
            params_schema = {"type": "object", "properties": {}}

            for param in ep["query_params"]:
                params_schema["properties"][param] = {"type": "string"}

            if ep["request_body_keys"]:
                params_schema["properties"]["body"] = {
                    "type": "object",
                    "properties": {k: {"type": "string"} for k in ep["request_body_keys"]},
                }

            action_name = self._generate_action_name(ep["method"], path)

            action = GeneratedAction(
                name=action_name,
                alias=self._slugify(action_name),
                description=f"{ep['method']} {path}",
                method=ep["method"],
                path=path,
                parameters_schema=params_schema,
            )

            resources_map[resource_name].actions.append(action)

        return list(resources_map.values())

    # =========================================================================
    # Save to Database
    # =========================================================================

    def save_to_database(self, system: GeneratedSystem, account_id: int | None = None) -> "System":  # noqa: F821
        """
        Save generated system to database.

        Args:
            system: GeneratedSystem to save
            account_id: Account to associate with (for AccountSystem)

        Returns:
            Created System model instance
        """
        from apps.systems.models import AccountSystem, Action, Interface, Resource, System

        # Create or update System
        db_system, created = System.objects.update_or_create(
            alias=system.alias,
            defaults={
                "name": system.name,
                "display_name": system.display_name,
                "description": system.description,
                "system_type": system.system_type,
                "website_url": system.website_url,
                "variables": system.variables,
                "is_active": True,
            },
        )

        # Create interfaces
        for iface in system.interfaces:
            db_interface, _ = Interface.objects.update_or_create(
                system=db_system,
                alias=iface.alias or iface.name,
                defaults={"name": iface.name, "type": iface.type, "base_url": iface.base_url, "auth": iface.auth},
            )

            # Create resources
            for res in iface.resources:
                db_resource, _ = Resource.objects.update_or_create(
                    interface=db_interface,
                    alias=res.alias or res.name,
                    defaults={"name": res.name, "description": res.description},
                )

                # Create actions
                for act in res.actions:
                    Action.objects.update_or_create(
                        resource=db_resource,
                        alias=act.alias or act.name,
                        defaults={
                            "name": act.name,
                            "description": act.description,
                            "method": act.method,
                            "path": act.path,
                            "parameters_schema": act.parameters_schema,
                            "output_schema": act.output_schema,
                            "headers": act.headers,
                        },
                    )

        # Create AccountSystem link if account_id provided
        target_account = account_id or self.account_id
        if target_account:
            AccountSystem.objects.get_or_create(
                account_id=target_account,
                system=db_system,
                defaults={"is_enabled": False},  # Not enabled until credentials are added
            )

        logger.info(f"Saved system '{system.alias}' with {sum(len(i.resources) for i in system.interfaces)} resources")

        return db_system

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _slugify(self, text: str) -> str:
        """Convert text to slug format."""
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = text.strip("_")
        return text or "unknown"

    def _extract_resource_name(self, path: str) -> str:
        """Extract resource name from path."""
        # Remove leading slash and split
        parts = path.strip("/").split("/")

        # Find first non-parameter part
        for part in parts:
            if not part.startswith("{") and part:
                return part

        return "root"

    def _generate_action_name(self, method: str, path: str) -> str:
        """Generate action name from method and path."""
        method = method.lower()
        resource = self._extract_resource_name(path)

        # Check if path has ID parameter
        has_id = "{" in path

        if method == "get":
            return f"get_{resource}" if has_id else f"list_{resource}"
        elif method == "post":
            return f"create_{resource}"
        elif method == "put":
            return f"update_{resource}"
        elif method == "patch":
            return f"patch_{resource}"
        elif method == "delete":
            return f"delete_{resource}"
        else:
            return f"{method}_{resource}"

    def _guess_system_type(self, name: str, spec: dict) -> str:
        """Guess system type from name and spec."""
        name_lower = name.lower()

        if any(k in name_lower for k in ["jira", "asana", "trello", "project", "task"]):
            return "project_management"
        if any(k in name_lower for k in ["slack", "teams", "discord", "chat", "message"]):
            return "communication"
        if any(k in name_lower for k in ["github", "gitlab", "bitbucket", "git"]):
            return "version_control"
        if any(k in name_lower for k in ["jenkins", "circleci", "travis", "deploy"]):
            return "ci_cd"
        if any(k in name_lower for k in ["datadog", "newrelic", "prometheus", "monitor"]):
            return "monitoring"
        if any(k in name_lower for k in ["s3", "storage", "blob", "file"]):
            return "storage"

        return "other"

    def to_dict(self, system: GeneratedSystem) -> dict:
        """Convert GeneratedSystem to dict for preview."""
        return asdict(system)

    def to_json(self, system: GeneratedSystem, indent: int = 2) -> str:
        """Convert GeneratedSystem to JSON string."""
        return json.dumps(self.to_dict(system), indent=indent)
