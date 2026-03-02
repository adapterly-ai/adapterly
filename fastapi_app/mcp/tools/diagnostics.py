"""
Error Diagnosis Engine + MCP diagnostic tools.

Core diagnosis logic is in gateway_core.diagnostics.
This module adds the MCP tool definitions for the monolith.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export core functions for backward compatibility
from gateway_core.diagnostics import diagnose_error, persist_diagnostic  # noqa: F401
from gateway_core.models import ErrorDiagnostic

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# MCP Tools (monolith only)
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
    row.reviewed_at = datetime.utcnow()
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
