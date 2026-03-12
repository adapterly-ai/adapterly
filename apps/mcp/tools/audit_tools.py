"""
MCP Audit Tools - Reasoning and rollback functionality.

These tools expose audit trail features to AI agents:
- Get explanations for why actions were taken
- View related actions (correlation)
- Rollback reversible actions
- Query audit history
"""

import logging
from typing import Any

from asgiref.sync import sync_to_async

from apps.mcp.tools.base import MCPTool, build_input_schema

logger = logging.getLogger(__name__)


async def explain_action_handler(ctx: dict[str, Any], audit_id: int) -> dict[str, Any]:
    """
    Get a human-readable explanation of why an action was taken.

    Returns the reasoning, intent, and context captured during the action.
    """
    from apps.mcp.models import MCPAuditLog

    account_id = ctx["account_id"]

    @sync_to_async
    def _get_explanation():
        try:
            entry = MCPAuditLog.objects.get(id=audit_id, account_id=account_id)
            return entry.get_explanation()
        except MCPAuditLog.DoesNotExist:
            return None

    explanation = await _get_explanation()

    if not explanation:
        return {"success": False, "error": f"Audit entry {audit_id} not found"}

    return {"success": True, "audit_id": audit_id, "explanation": explanation}


async def get_related_actions_handler(ctx: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    """
    Get all actions related by correlation ID.

    Actions performed as part of the same logical operation share a correlation ID.
    """
    from apps.mcp.models import MCPAuditLog

    account_id = ctx["account_id"]

    @sync_to_async
    def _get_related():
        entries = MCPAuditLog.objects.filter(account_id=account_id, correlation_id=correlation_id).order_by("timestamp")

        return [
            {
                "audit_id": e.id,
                "tool_name": e.tool_name,
                "timestamp": e.timestamp.isoformat(),
                "success": e.success,
                "intent": e.intent,
                "reasoning": e.reasoning[:200] if e.reasoning else "",
            }
            for e in entries
        ]

    related = await _get_related()

    return {"success": True, "correlation_id": correlation_id, "actions": related, "count": len(related)}


async def rollback_action_handler(ctx: dict[str, Any], audit_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Rollback a reversible action.

    First call without confirm=True to see what will be rolled back.
    Then call with confirm=True to execute the rollback.
    """
    from apps.mcp.models import MCPAuditLog

    account_id = ctx["account_id"]
    audit_logger = ctx.get("audit")

    @sync_to_async
    def _get_entry():
        try:
            return MCPAuditLog.objects.get(id=audit_id, account_id=account_id)
        except MCPAuditLog.DoesNotExist:
            return None

    entry = await _get_entry()

    if not entry:
        return {"success": False, "error": f"Audit entry {audit_id} not found"}

    if not entry.is_reversible:
        return {
            "success": False,
            "error": "This action is not reversible",
            "audit_id": audit_id,
            "tool_name": entry.tool_name,
        }

    if entry.rolled_back:
        return {
            "success": False,
            "error": "This action has already been rolled back",
            "audit_id": audit_id,
            "rolled_back_at": entry.rolled_back_at.isoformat() if entry.rolled_back_at else None,
        }

    # Preview mode - show what will be rolled back
    if not confirm:
        return {
            "success": True,
            "preview": True,
            "audit_id": audit_id,
            "tool_name": entry.tool_name,
            "timestamp": entry.timestamp.isoformat(),
            "rollback_data": entry.rollback_data,
            "message": "Set confirm=True to execute rollback",
        }

    # Execute rollback
    try:
        # Perform the rollback based on the stored rollback_data
        rollback_result = await _execute_rollback(ctx, entry)

        # Log the rollback
        if audit_logger and rollback_result.get("success"):
            await sync_to_async(audit_logger.log_rollback)(
                original_audit_id=audit_id,
                tool_name=entry.tool_name,
                parameters=entry.rollback_data,
                result=rollback_result,
                error=rollback_result.get("error"),
            )

        return {
            "success": rollback_result.get("success", False),
            "audit_id": audit_id,
            "rollback_result": rollback_result,
            "message": "Rollback executed" if rollback_result.get("success") else "Rollback failed",
        }

    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        return {"success": False, "error": str(e), "audit_id": audit_id}


async def _execute_rollback(ctx: dict[str, Any], entry) -> dict[str, Any]:
    """
    Execute the actual rollback operation.

    This is a generic implementation that handles common rollback patterns.
    For specific systems, this could be extended with custom rollback logic.
    """
    rollback_data = entry.rollback_data or {}

    # Check for explicit rollback action
    rollback_action = rollback_data.get("rollback_action")
    if rollback_action:
        # TODO: Execute the specified rollback action
        return {"success": False, "error": "Custom rollback actions not yet implemented"}

    # Check for delete-to-restore pattern
    if rollback_data.get("type") == "restore_deleted":
        # TODO: Implement restore logic
        return {"success": False, "error": "Restore from delete not yet implemented"}

    # Check for create-to-delete pattern
    if rollback_data.get("type") == "delete_created":
        created_id = rollback_data.get("created_id")
        system = rollback_data.get("system")

        if not created_id or not system:
            return {"success": False, "error": "Missing created_id or system in rollback data"}

        # TODO: Execute delete action
        return {"success": False, "error": "Delete rollback not yet implemented", "would_delete": created_id}

    # Check for update-to-restore pattern
    if rollback_data.get("type") == "restore_previous":
        previous_value = rollback_data.get("previous_value")
        resource_id = rollback_data.get("resource_id")

        if not previous_value or not resource_id:
            return {"success": False, "error": "Missing previous_value or resource_id in rollback data"}

        # TODO: Execute update with previous value
        return {"success": False, "error": "Update rollback not yet implemented", "would_restore": previous_value}

    return {"success": False, "error": "Unknown rollback type", "rollback_data": rollback_data}


async def query_audit_handler(
    ctx: dict[str, Any],
    tool_name: str | None = None,
    success: bool | None = None,
    limit: int = 20,
    include_reasoning: bool = False,
) -> dict[str, Any]:
    """
    Query audit log entries.

    Returns recent actions with optional filtering.
    """
    from apps.mcp.models import MCPAuditLog

    account_id = ctx["account_id"]

    @sync_to_async
    def _query():
        qs = MCPAuditLog.objects.filter(account_id=account_id)

        if tool_name:
            qs = qs.filter(tool_name__icontains=tool_name)

        if success is not None:
            qs = qs.filter(success=success)

        qs = qs.order_by("-timestamp")[:limit]

        results = []
        for entry in qs:
            item = {
                "audit_id": entry.id,
                "tool_name": entry.tool_name,
                "tool_type": entry.tool_type,
                "timestamp": entry.timestamp.isoformat(),
                "success": entry.success,
                "duration_ms": entry.duration_ms,
                "is_reversible": entry.is_reversible,
                "rolled_back": entry.rolled_back,
            }

            if include_reasoning:
                item["intent"] = entry.intent
                item["reasoning"] = entry.reasoning[:300] if entry.reasoning else ""

            if entry.error_message:
                item["error"] = entry.error_message[:200]

            results.append(item)

        return results

    results = await _query()

    return {"success": True, "entries": results, "count": len(results)}


def get_audit_tools() -> list[MCPTool]:
    """Get all audit-related tools."""
    return [
        MCPTool(
            name="explain_action",
            description="Get a human-readable explanation of why an action was taken, including AI reasoning and context.",
            llm_description="Explain why an action was taken. Shows AI reasoning captured during execution.",
            tool_hints="Use this to understand the reasoning behind any audit entry. Returns the intent, reasoning, and context.",
            input_schema=build_input_schema(
                {"audit_id": {"type": "integer", "description": "The audit entry ID to explain"}}, required=["audit_id"]
            ),
            handler=explain_action_handler,
            tool_type="system_read",
            examples=[
                {
                    "description": "Get explanation for an action",
                    "input": {"audit_id": 123},
                    "output": {
                        "success": True,
                        "explanation": {
                            "what": "Called salesforce_contact_create",
                            "why": "User requested to add a new lead",
                            "intent": "Create sales lead",
                        },
                    },
                }
            ],
        ),
        MCPTool(
            name="get_related_actions",
            description="Get all actions that were part of the same logical operation (share a correlation ID).",
            llm_description="Find actions related by correlation ID. Shows grouped operations.",
            tool_hints="Use when you need to see all steps of a multi-step operation. Returns chronologically ordered actions.",
            input_schema=build_input_schema(
                {"correlation_id": {"type": "string", "description": "The correlation ID to search for"}},
                required=["correlation_id"],
            ),
            handler=get_related_actions_handler,
            tool_type="system_read",
        ),
        MCPTool(
            name="rollback_action",
            description="Rollback a reversible action. First call without confirm to preview, then with confirm=True to execute.",
            llm_description="Undo a reversible action. Preview first, then confirm to execute.",
            tool_hints="Only works on actions marked as reversible. Always preview first by calling without confirm=True. Be careful with rollbacks.",
            input_schema=build_input_schema(
                {
                    "audit_id": {"type": "integer", "description": "The audit entry ID of the action to rollback"},
                    "confirm": {
                        "type": "boolean",
                        "description": "Set to true to execute rollback (default: false for preview)",
                    },
                },
                required=["audit_id"],
            ),
            handler=rollback_action_handler,
            tool_type="system_write",
            examples=[
                {
                    "description": "Preview a rollback",
                    "input": {"audit_id": 456},
                    "output": {
                        "success": True,
                        "preview": True,
                        "tool_name": "salesforce_contact_create",
                        "message": "Set confirm=True to execute",
                    },
                },
                {
                    "description": "Execute rollback",
                    "input": {"audit_id": 456, "confirm": True},
                    "output": {"success": True, "message": "Rollback executed"},
                },
            ],
        ),
        MCPTool(
            name="query_audit",
            description="Query recent audit log entries with optional filtering.",
            llm_description="Search audit logs. Filter by tool name or success status.",
            tool_hints="Use to review recent actions. Set include_reasoning=True to see AI reasoning. Useful for debugging or compliance.",
            input_schema=build_input_schema(
                {
                    "tool_name": {"type": "string", "description": "Filter by tool name (partial match)"},
                    "success": {"type": "boolean", "description": "Filter by success status"},
                    "limit": {"type": "integer", "description": "Max entries to return (default: 20, max: 100)"},
                    "include_reasoning": {
                        "type": "boolean",
                        "description": "Include AI reasoning in results (default: false)",
                    },
                }
            ),
            handler=query_audit_handler,
            tool_type="system_read",
            examples=[
                {
                    "description": "Find recent failed actions",
                    "input": {"success": False, "limit": 10, "include_reasoning": True},
                    "output": {
                        "success": True,
                        "count": 3,
                        "entries": [{"tool_name": "salesforce_contact_update", "success": False}],
                    },
                }
            ],
        ),
    ]
