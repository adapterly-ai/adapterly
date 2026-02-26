"""
Error Diagnosis Engine + MCP diagnostic tools.

Classifies adapter errors (auth, 404, validation, rate limit, etc.),
suggests fixes, and persists diagnostics for review.
Fixes always require manual approval.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.mcp import ErrorDiagnostic

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Error classification rules
# --------------------------------------------------------------------------- #

_AUTH_EXPIRED_PATTERNS = [
    "token expired",
    "token has expired",
    "jwt expired",
    "access token expired",
    "oauth token expired",
    "token_expired",
]

_AUTH_PERMISSION_PATTERNS = [
    "permission",
    "forbidden",
    "insufficient",
    "not authorized",
    "access denied",
    "scope",
    "privilege",
]


def _lower_contains(text: str, patterns: list[str]) -> bool:
    """Check if lowered text contains any of the patterns."""
    lower = text.lower()
    return any(p in lower for p in patterns)


def diagnose_error(
    system_alias: str,
    tool_name: str,
    action_name: str,
    error_result: dict[str, Any],
    account_system: Any = None,
    request_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify an error result and produce a diagnosis dict.

    Returns a dict with keys:
        category, severity, diagnosis_summary, diagnosis_detail,
        has_fix, fix_description, fix_action, status_code, error_data
    """
    error_msg = error_result.get("error", "")
    status_code = error_result.get("status_code")
    error_data = error_result.get("error_data") or {}
    error_str = f"{error_msg} {str(error_data)}".lower()

    # Detect timeout / connection errors (no HTTP status)
    if status_code is None:
        if any(kw in error_str for kw in ["timeout", "timed out", "timedout"]):
            return _build(
                category="timeout",
                severity="medium",
                summary=f"Request to {system_alias} timed out",
                detail=error_msg,
                status_code=status_code,
                error_data=error_data,
            )
        if any(
            kw in error_str
            for kw in [
                "connection",
                "connect",
                "refused",
                "unreachable",
                "dns",
                "network",
                "eof",
                "reset",
            ]
        ):
            return _build(
                category="connection",
                severity="high",
                summary=f"Cannot connect to {system_alias}",
                detail=error_msg,
                status_code=status_code,
                error_data=error_data,
            )

    # --- HTTP status based classification --- #

    if status_code in (401, 403):
        # OAuth expired?
        if _lower_contains(error_str, _AUTH_EXPIRED_PATTERNS):
            has_refresh = bool(account_system and getattr(account_system, "oauth_refresh_token", None))
            # DRF token auth can also auto-refresh using stored credentials
            has_drf_credentials = bool(
                account_system
                and getattr(account_system, "username", None)
                and getattr(account_system, "password", None)
            )
            can_auto_refresh = has_refresh or has_drf_credentials

            if has_drf_credentials and not has_refresh:
                fix_desc = "Auto-refresh DRF token using stored username/password credentials"
                fix_act = {"type": "refresh_drf_token", "system_alias": system_alias}
            elif has_refresh:
                fix_desc = "Refresh the OAuth token using the stored refresh token"
                fix_act = {"type": "refresh_oauth", "system_alias": system_alias}
            else:
                fix_desc = ""
                fix_act = {}

            return _build(
                category="auth_expired",
                severity="high",
                summary=f"Token expired for {system_alias}",
                detail=error_msg,
                status_code=status_code,
                error_data=error_data,
                has_fix=can_auto_refresh,
                fix_description=fix_desc,
                fix_action=fix_act,
            )
        # Permission issue?
        if _lower_contains(error_str, _AUTH_PERMISSION_PATTERNS):
            return _build(
                category="auth_permissions",
                severity="high",
                summary=f"Insufficient permissions on {system_alias}",
                detail=error_msg,
                status_code=status_code,
                error_data=error_data,
            )
        # Generic auth failure
        return _build(
            category="auth_invalid",
            severity="high",
            summary=f"Authentication failed for {system_alias}",
            detail=error_msg,
            status_code=status_code,
            error_data=error_data,
            fix_description="Check that credentials / API key are valid and not revoked",
            fix_action={"type": "check_credentials", "system_alias": system_alias},
            has_fix=True,
        )

    if status_code == 404:
        # Entity mapping mismatch?
        if request_params and any(k in (request_params or {}) for k in ["project_id", "projectId", "project_uuid"]):
            return _build(
                category="not_found_mapping",
                severity="medium",
                summary=f"Entity not found in {system_alias} — check entity mapping",
                detail=error_msg,
                status_code=status_code,
                error_data=error_data,
                has_fix=True,
                fix_description="Verify the entity mapping IDs match the external system",
                fix_action={"type": "check_mapping", "system_alias": system_alias},
            )
        return _build(
            category="not_found_path",
            severity="medium",
            summary=f"Resource not found on {system_alias} (404)",
            detail=error_msg,
            status_code=status_code,
            error_data=error_data,
        )

    if status_code in (400, 422):
        if any(kw in error_str for kw in ["required", "missing", "mandatory"]):
            return _build(
                category="validation_missing",
                severity="medium",
                summary=f"Required fields missing for {system_alias}",
                detail=error_msg,
                status_code=status_code,
                error_data=error_data,
            )
        return _build(
            category="validation_type",
            severity="medium",
            summary=f"Validation error from {system_alias}",
            detail=error_msg,
            status_code=status_code,
            error_data=error_data,
        )

    if status_code == 429:
        retry_after = None
        if isinstance(error_data, dict):
            retry_after = error_data.get("retry-after") or error_data.get("Retry-After")
        return _build(
            category="rate_limit",
            severity="low",
            summary=f"Rate limit exceeded on {system_alias}",
            detail=error_msg,
            status_code=status_code,
            error_data=error_data,
            has_fix=True,
            fix_description=f"Wait and retry (Retry-After: {retry_after})"
            if retry_after
            else "Wait and retry the request",
            fix_action={"type": "retry_after", "seconds": retry_after},
        )

    if status_code and status_code >= 500:
        return _build(
            category="server_error",
            severity="high",
            summary=f"Server error from {system_alias} (HTTP {status_code})",
            detail=error_msg,
            status_code=status_code,
            error_data=error_data,
        )

    # Fallback
    return _build(
        category="unknown",
        severity="medium",
        summary=f"Error from {system_alias}: {error_msg[:200]}",
        detail=error_msg,
        status_code=status_code,
        error_data=error_data,
    )


def _build(
    *,
    category: str,
    severity: str,
    summary: str,
    detail: str,
    status_code: int | None,
    error_data: Any,
    has_fix: bool = False,
    fix_description: str = "",
    fix_action: dict | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "diagnosis_summary": summary[:500],
        "diagnosis_detail": detail,
        "status_code": status_code,
        "error_data": error_data if isinstance(error_data, dict) else {},
        "has_fix": has_fix,
        "fix_description": fix_description,
        "fix_action": fix_action or {},
    }


# --------------------------------------------------------------------------- #
# Persistence (dedup)
# --------------------------------------------------------------------------- #


async def persist_diagnostic(
    db: AsyncSession,
    account_id: int,
    system_alias: str,
    tool_name: str,
    action_name: str,
    error_message: str,
    diag: dict[str, Any],
) -> int:
    """
    Persist or deduplicate an error diagnostic.

    Dedup key: (account_id, system_alias, category, tool_name, status='pending').
    Returns the diagnostic row id.
    """
    now = datetime.now(timezone.utc)

    # Look for existing pending diagnostic with same key
    stmt = select(ErrorDiagnostic).where(
        and_(
            ErrorDiagnostic.account_id == account_id,
            ErrorDiagnostic.system_alias == system_alias,
            ErrorDiagnostic.category == diag["category"],
            ErrorDiagnostic.tool_name == tool_name,
            ErrorDiagnostic.status == "pending",
        )
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = now
        existing.error_message = error_message
        existing.error_data = diag.get("error_data", {})
        existing.diagnosis_summary = diag["diagnosis_summary"]
        existing.diagnosis_detail = diag.get("diagnosis_detail", "")
        await db.commit()
        return existing.id

    row = ErrorDiagnostic(
        account_id=account_id,
        system_alias=system_alias,
        tool_name=tool_name,
        action_name=action_name or "",
        status_code=diag.get("status_code"),
        error_message=error_message,
        error_data=diag.get("error_data", {}),
        category=diag["category"],
        severity=diag.get("severity", "medium"),
        diagnosis_summary=diag["diagnosis_summary"],
        diagnosis_detail=diag.get("diagnosis_detail", ""),
        has_fix=diag.get("has_fix", False),
        fix_description=diag.get("fix_description", ""),
        fix_action=diag.get("fix_action", {}),
        status="pending",
        occurrence_count=1,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row.id


# --------------------------------------------------------------------------- #
# MCP Tools
# --------------------------------------------------------------------------- #


async def _handle_get_diagnostics(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """List pending error diagnostics for the account."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")
    if not db:
        return {"error": "Database session not available"}

    system_alias = kwargs.get("system_alias")
    status_filter = kwargs.get("status", "pending")
    limit = min(int(kwargs.get("limit", 20)), 50)

    conditions = [ErrorDiagnostic.account_id == account_id]
    if system_alias:
        conditions.append(ErrorDiagnostic.system_alias == system_alias)
    if status_filter:
        conditions.append(ErrorDiagnostic.status == status_filter)

    stmt = select(ErrorDiagnostic).where(and_(*conditions)).order_by(ErrorDiagnostic.last_seen_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "system_alias": r.system_alias,
                "tool_name": r.tool_name,
                "category": r.category,
                "severity": r.severity,
                "summary": r.diagnosis_summary,
                "has_fix": r.has_fix,
                "fix_description": r.fix_description if r.has_fix else None,
                "occurrence_count": r.occurrence_count,
                "last_seen": r.last_seen_at.isoformat() if r.last_seen_at else None,
                "status": r.status,
            }
        )

    return {"diagnostics": items, "count": len(items)}


async def _handle_dismiss_diagnostic(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Dismiss a pending diagnostic."""
    db: AsyncSession = ctx.get("db")
    account_id = ctx.get("account_id")
    if not db:
        return {"error": "Database session not available"}

    diag_id = kwargs.get("diagnostic_id")
    if not diag_id:
        return {"error": "diagnostic_id is required"}

    stmt = select(ErrorDiagnostic).where(
        and_(
            ErrorDiagnostic.id == int(diag_id),
            ErrorDiagnostic.account_id == account_id,
        )
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        return {"error": f"Diagnostic {diag_id} not found"}
    if row.status != "pending":
        return {"error": f"Diagnostic {diag_id} is not pending (status: {row.status})"}

    notes = kwargs.get("notes", "")
    row.status = "dismissed"
    row.reviewed_at = datetime.now(timezone.utc)
    row.review_notes = notes
    await db.commit()

    return {"success": True, "diagnostic_id": row.id, "new_status": "dismissed"}


def get_diagnostic_tools() -> list[dict[str, Any]]:
    """Return MCP tool definitions for diagnostics."""
    return [
        {
            "name": "get_diagnostics",
            "description": (
                "List error diagnostics for the current account. "
                "Shows categorized errors from system integrations with fix suggestions. "
                "Filter by system_alias or status."
            ),
            "tool_type": "context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "system_alias": {
                        "type": "string",
                        "description": "Filter by system alias (e.g. 'infrakit', 'jira')",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status (default: 'pending')",
                        "enum": ["pending", "approved", "dismissed", "applied", "expired"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20, max 50)",
                    },
                },
            },
            "handler": _handle_get_diagnostics,
        },
        {
            "name": "dismiss_diagnostic",
            "description": (
                "Dismiss a pending error diagnostic. Use this when the error has been resolved or is not relevant."
            ),
            "tool_type": "context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "diagnostic_id": {
                        "type": "integer",
                        "description": "ID of the diagnostic to dismiss",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional review notes",
                    },
                },
                "required": ["diagnostic_id"],
            },
            "handler": _handle_dismiss_diagnostic,
        },
    ]
