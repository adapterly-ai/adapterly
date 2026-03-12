"""HTTP client for Adapterly REST API."""

import httpx


class AdapterlyClient:
    """Thin client wrapping /api/v1/tools/ REST endpoints."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/tools/{path}"

    def list_tools(self, search: str | None = None, fmt: str = "simple") -> dict:
        """List available tools."""
        params = {"format": fmt}
        if search:
            params["search"] = search

        resp = httpx.get(
            self._url(""),
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        """Call a tool by name with optional arguments."""
        resp = httpx.post(
            self._url(f"{tool_name}/call"),
            headers=self._headers(),
            json=arguments or {},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
