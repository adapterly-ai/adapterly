"""Error classification for tool execution failures."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_AUTH_EXPIRED_PATTERNS = [
    "token expired", "token has expired", "jwt expired",
    "access token expired", "oauth token expired", "token_expired",
]

_AUTH_PERMISSION_PATTERNS = [
    "permission", "forbidden", "insufficient",
    "not authorized", "access denied", "scope", "privilege",
]


def _lower_contains(text: str, patterns: list[str]) -> bool:
    lower = text.lower()
    return any(p in lower for p in patterns)


def diagnose_error(
    integration_slug: str,
    tool_name: str,
    error_result: dict[str, Any],
) -> dict[str, Any]:
    """Classify an error and return a diagnosis dict."""
    error_msg = error_result.get("error", "")
    status_code = error_result.get("status_code")
    error_data = error_result.get("error_data") or {}
    error_str = f"{error_msg} {str(error_data)}".lower()

    if status_code is None:
        if any(kw in error_str for kw in ["timeout", "timed out"]):
            return _build("timeout", "medium", f"Request to {integration_slug} timed out", error_msg, status_code)
        if any(kw in error_str for kw in ["connection", "refused", "unreachable", "dns"]):
            return _build("connection", "high", f"Cannot connect to {integration_slug}", error_msg, status_code)

    if status_code in (401, 403):
        if _lower_contains(error_str, _AUTH_EXPIRED_PATTERNS):
            return _build("auth_expired", "high", f"Token expired for {integration_slug}", error_msg, status_code)
        if _lower_contains(error_str, _AUTH_PERMISSION_PATTERNS):
            return _build("auth_permissions", "high", f"Insufficient permissions on {integration_slug}", error_msg, status_code)
        return _build("auth_invalid", "high", f"Authentication failed for {integration_slug}", error_msg, status_code)

    if status_code == 404:
        return _build("not_found", "medium", f"Resource not found on {integration_slug}", error_msg, status_code)

    if status_code in (400, 422):
        return _build("validation", "medium", f"Validation error from {integration_slug}", error_msg, status_code)

    if status_code == 429:
        return _build("rate_limit", "low", f"Rate limit exceeded on {integration_slug}", error_msg, status_code)

    if status_code and status_code >= 500:
        return _build("server_error", "high", f"Server error from {integration_slug} ({status_code})", error_msg, status_code)

    return _build("unknown", "medium", f"Error from {integration_slug}: {error_msg[:200]}", error_msg, status_code)


def _build(category: str, severity: str, summary: str, detail: str, status_code: int | None) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "summary": summary[:500],
        "detail": detail,
        "status_code": status_code,
    }
