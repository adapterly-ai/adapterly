"""
MCP Audit logging system.

Enhanced with:
- AI reasoning capture ("why did the AI do this")
- Rollback tracking for reversible actions
- Correlation IDs for multi-step operations
"""

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class ReasoningContext:
    """
    Captures AI agent reasoning for audit logging.

    This enables "why did the AI do this" explanations in the audit trail.
    """

    reasoning: str = ""  # The agent's reasoning for this action
    intent: str = ""  # High-level intent (e.g., "Retrieve customer data")
    context_summary: str = ""  # Summary of conversation context
    correlation_id: str = ""  # Groups related actions together
    parent_audit_id: int | None = None  # For nested operations


@dataclass
class RollbackContext:
    """
    Captures data needed for rollback support.
    """

    is_reversible: bool = False
    rollback_data: dict[str, Any] = field(default_factory=dict)


class MCPAuditLogger:
    """
    Audit logger for MCP tool calls.

    Logs all tool calls with parameters, results, timing, and AI reasoning.

    Enhanced features:
    - Reasoning capture: Records why the AI took an action
    - Rollback tracking: Tracks reversible actions and their undo data
    - Correlation: Groups related audit entries together
    """

    def __init__(
        self,
        account_id: int,
        session_id: str = "",
        user_id: int | None = None,
        transport: str = "stdio",
        mode: str = "safe",
    ):
        """
        Initialize audit logger.

        Args:
            account_id: Account ID
            session_id: MCP session identifier
            user_id: Optional user ID
            transport: Transport type (stdio, sse)
            mode: Permission mode (safe, power)
        """
        self.account_id = account_id
        self.session_id = session_id
        self.user_id = user_id
        self.transport = transport
        self.mode = mode

        # Current reasoning context (can be set before tool calls)
        self._reasoning_context: ReasoningContext | None = None

    def set_reasoning_context(
        self, reasoning: str = "", intent: str = "", context_summary: str = "", correlation_id: str = ""
    ):
        """
        Set reasoning context for subsequent tool calls.

        Call this before making tool calls to capture AI reasoning.

        Args:
            reasoning: Why the AI is taking this action
            intent: High-level intent of the action
            context_summary: Summary of conversation context
            correlation_id: ID to group related actions (auto-generated if empty)
        """
        self._reasoning_context = ReasoningContext(
            reasoning=reasoning,
            intent=intent,
            context_summary=context_summary,
            correlation_id=correlation_id or str(uuid.uuid4())[:8],
        )

    def clear_reasoning_context(self):
        """Clear the current reasoning context."""
        self._reasoning_context = None

    def log_tool_call(
        self,
        tool_name: str,
        tool_type: str,
        parameters: dict,
        result: Any = None,
        duration_ms: int = 0,
        error: str | None = None,
        reasoning: ReasoningContext | None = None,
        rollback: RollbackContext | None = None,
    ) -> int | None:
        """
        Log a tool call.

        Args:
            tool_name: Name of the tool called
            tool_type: Type of tool (system_read, system_write, resource, context)
            parameters: Parameters passed to the tool
            result: Result of the tool call
            duration_ms: Execution time in milliseconds
            error: Error message if call failed
            reasoning: Optional reasoning context (uses stored context if not provided)
            rollback: Optional rollback context for reversible actions

        Returns:
            The audit log entry ID, or None if logging failed
        """
        from apps.mcp.models import MCPAuditLog

        # Use provided reasoning or fall back to stored context
        ctx = reasoning or self._reasoning_context or ReasoningContext()
        rb = rollback or RollbackContext()

        try:
            audit_entry = MCPAuditLog.objects.create(
                account_id=self.account_id,
                user_id=self.user_id,
                tool_name=tool_name,
                tool_type=tool_type,
                parameters=self._sanitize_params(parameters),
                result_summary=self._summarize_result(result),
                duration_ms=duration_ms,
                success=error is None,
                error_message=error or "",
                session_id=self.session_id,
                transport=self.transport,
                mode=self.mode,
                timestamp=timezone.now(),
                # Reasoning fields
                reasoning=ctx.reasoning,
                intent=ctx.intent,
                context_summary=ctx.context_summary,
                correlation_id=ctx.correlation_id,
                parent_audit_id=ctx.parent_audit_id,
                # Rollback fields
                is_reversible=rb.is_reversible,
                rollback_data=rb.rollback_data,
            )
            return audit_entry.id
        except Exception as e:
            # Never fail the tool call due to audit logging
            logger.error(f"Failed to log audit: {e}")
            return None

    def log_rollback(
        self,
        original_audit_id: int,
        tool_name: str,
        parameters: dict,
        result: Any = None,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> int | None:
        """
        Log a rollback action and update the original entry.

        Args:
            original_audit_id: ID of the audit entry being rolled back
            tool_name: Name of the rollback tool
            parameters: Parameters for the rollback
            result: Result of the rollback
            duration_ms: Execution time
            error: Error message if rollback failed

        Returns:
            The rollback audit entry ID, or None if failed
        """
        from apps.mcp.models import MCPAuditLog

        # Create reasoning context for rollback
        reasoning = ReasoningContext(
            reasoning=f"Rolling back action from audit entry {original_audit_id}",
            intent="Undo previous action",
        )

        # Log the rollback action
        rollback_id = self.log_tool_call(
            tool_name=f"rollback:{tool_name}",
            tool_type="system_write",
            parameters=parameters,
            result=result,
            duration_ms=duration_ms,
            error=error,
            reasoning=reasoning,
        )

        # Update the original entry if rollback was logged
        if rollback_id and error is None:
            try:
                original = MCPAuditLog.objects.get(id=original_audit_id)
                original.mark_rolled_back(rollback_id)
            except MCPAuditLog.DoesNotExist:
                logger.warning(f"Original audit entry {original_audit_id} not found")

        return rollback_id

    def get_explanation(self, audit_id: int) -> dict | None:
        """
        Get a human-readable explanation for an audit entry.

        Args:
            audit_id: The audit entry ID

        Returns:
            Explanation dict or None if not found
        """
        from apps.mcp.models import MCPAuditLog

        try:
            entry = MCPAuditLog.objects.get(id=audit_id, account_id=self.account_id)
            return entry.get_explanation()
        except MCPAuditLog.DoesNotExist:
            return None

    def get_related_entries(self, correlation_id: str) -> list:
        """
        Get all audit entries with the same correlation ID.

        Args:
            correlation_id: The correlation ID to search for

        Returns:
            List of related audit entries
        """
        from apps.mcp.models import MCPAuditLog

        entries = MCPAuditLog.objects.filter(account_id=self.account_id, correlation_id=correlation_id).order_by(
            "timestamp"
        )

        return [e.get_explanation() for e in entries]

    def _sanitize_params(self, params: dict) -> dict:
        """
        Sanitize parameters for logging.
        Remove sensitive data like passwords, tokens, etc.
        """
        if not isinstance(params, dict):
            return {"value": str(params)[:1000]}

        sanitized = {}
        sensitive_keys = {
            "password",
            "token",
            "api_key",
            "secret",
            "credential",
            "auth",
            "authorization",
            "cookie",
            "session",
        }

        for key, value in params.items():
            lower_key = key.lower()
            if any(s in lower_key for s in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_params(value)
            elif isinstance(value, str) and len(value) > 1000:
                sanitized[key] = value[:1000] + "... [truncated]"
            else:
                sanitized[key] = value

        return sanitized

    def _summarize_result(self, result: Any) -> dict:
        """
        Create a summary of the result for logging.
        """
        if result is None:
            return {"status": "no_result"}

        if isinstance(result, dict):
            # Keep structure but limit size
            return self._truncate_dict(result, max_depth=3, max_items=20)

        if isinstance(result, list):
            return {"type": "list", "count": len(result), "sample": result[:3] if result else []}

        if isinstance(result, str):
            if len(result) > 500:
                return {"type": "string", "length": len(result), "preview": result[:500]}
            return {"type": "string", "value": result}

        return {"type": type(result).__name__, "value": str(result)[:500]}

    def _truncate_dict(self, d: dict, max_depth: int, max_items: int) -> dict:
        """Truncate dict for logging."""
        if max_depth <= 0:
            return {"[truncated]": "max depth reached"}

        result = {}
        for i, (key, value) in enumerate(d.items()):
            if i >= max_items:
                result["[...]"] = f"{len(d) - max_items} more items"
                break

            if isinstance(value, dict):
                result[key] = self._truncate_dict(value, max_depth - 1, max_items)
            elif isinstance(value, list):
                result[key] = {"type": "list", "count": len(value)}
            elif isinstance(value, str) and len(value) > 200:
                result[key] = value[:200] + "..."
            else:
                result[key] = value

        return result

    @contextmanager
    def timed_call(
        self,
        tool_name: str,
        tool_type: str,
        parameters: dict,
        reasoning: ReasoningContext | None = None,
        rollback: RollbackContext | None = None,
    ):
        """
        Context manager for timing and logging tool calls.

        Usage:
            with audit.timed_call("tool_name", "system_read", params) as ctx:
                result = do_something()
                ctx.set_result(result)

            # With reasoning:
            reasoning = ReasoningContext(
                reasoning="User requested customer list",
                intent="Retrieve customer data"
            )
            with audit.timed_call("tool", "system_read", params, reasoning=reasoning) as ctx:
                ...

            # With rollback support:
            rollback = RollbackContext(
                is_reversible=True,
                rollback_data={"original_id": 123}
            )
            with audit.timed_call("tool", "system_write", params, rollback=rollback) as ctx:
                ...
        """
        start = time.perf_counter()

        class Context:
            def __init__(ctx_self):
                ctx_self.result = None
                ctx_self.error = None
                ctx_self.audit_id = None
                ctx_self._reasoning = reasoning
                ctx_self._rollback = rollback

            def set_result(ctx_self, result):
                ctx_self.result = result

            def set_error(ctx_self, error):
                ctx_self.error = str(error)

            def set_reasoning(ctx_self, reasoning: str, intent: str = "", context: str = ""):
                """Set reasoning after the fact."""
                ctx_self._reasoning = ReasoningContext(reasoning=reasoning, intent=intent, context_summary=context)

            def set_rollback_data(ctx_self, data: dict, is_reversible: bool = True):
                """Mark this action as reversible with rollback data."""
                ctx_self._rollback = RollbackContext(is_reversible=is_reversible, rollback_data=data)

        ctx = Context()

        try:
            yield ctx
        except Exception as e:
            ctx.error = str(e)
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            ctx.audit_id = self.log_tool_call(
                tool_name=tool_name,
                tool_type=tool_type,
                parameters=parameters,
                result=ctx.result,
                duration_ms=duration_ms,
                error=ctx.error,
                reasoning=ctx._reasoning,
                rollback=ctx._rollback,
            )


def audit_tool_call(tool_type: str):
    """
    Decorator for auditing tool calls.

    Args:
        tool_type: Type of tool (system_read, system_write, resource, context)

    Usage:
        @audit_tool_call("system_read")
        async def my_tool(ctx, params):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            audit = ctx.get("audit")
            if not audit:
                return await func(ctx, *args, **kwargs)

            tool_name = func.__name__
            parameters = kwargs.copy()
            if args:
                parameters["_args"] = list(args)

            with audit.timed_call(tool_name, tool_type, parameters) as audit_ctx:
                result = await func(ctx, *args, **kwargs)
                audit_ctx.set_result(result)
                return result

        return wrapper

    return decorator
