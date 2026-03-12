"""
Tests for MCP audit logging.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Account
from apps.mcp.audit import MCPAuditLogger
from apps.mcp.models import MCPAuditLog

User = get_user_model()


class TestMCPAuditLogger(TestCase):
    """Tests for MCPAuditLogger."""

    def setUp(self):
        self.account = Account.objects.create(name="Test Account")
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.logger = MCPAuditLogger(
            account_id=self.account.id,
            session_id="test_session_123",
            user_id=self.user.id,
            transport="stdio",
            mode="safe",
        )

    def test_log_tool_call_success(self):
        """Should log successful tool call."""
        self.logger.log_tool_call(
            tool_name="test_tool",
            tool_type="system_read",
            parameters={"id": 123},
            result={"success": True},
            duration_ms=50,
        )

        log = MCPAuditLog.objects.get(tool_name="test_tool")
        self.assertEqual(log.account_id, self.account.id)
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.tool_type, "system_read")
        self.assertTrue(log.success)
        self.assertEqual(log.duration_ms, 50)
        self.assertEqual(log.session_id, "test_session_123")

    def test_log_tool_call_error(self):
        """Should log failed tool call."""
        self.logger.log_tool_call(
            tool_name="failing_tool",
            tool_type="system_write",
            parameters={},
            result=None,
            duration_ms=100,
            error="Something went wrong",
        )

        log = MCPAuditLog.objects.get(tool_name="failing_tool")
        self.assertFalse(log.success)
        self.assertEqual(log.error_message, "Something went wrong")

    def test_sanitize_sensitive_params(self):
        """Should redact sensitive parameters."""
        params = {"username": "user", "password": "secret123", "api_key": "ak_123456", "data": {"token": "xyz"}}

        sanitized = self.logger._sanitize_params(params)

        self.assertEqual(sanitized["username"], "user")
        self.assertEqual(sanitized["password"], "[REDACTED]")
        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["data"]["token"], "[REDACTED]")

    def test_summarize_result_dict(self):
        """Should summarize dict results."""
        result = {"users": [{"id": 1}, {"id": 2}], "total": 2}

        summary = self.logger._summarize_result(result)

        self.assertIn("users", summary)
        self.assertEqual(summary["total"], 2)

    def test_summarize_result_list(self):
        """Should summarize list results."""
        result = [1, 2, 3, 4, 5]

        summary = self.logger._summarize_result(result)

        self.assertEqual(summary["type"], "list")
        self.assertEqual(summary["count"], 5)

    def test_summarize_long_string(self):
        """Should truncate long strings."""
        result = "x" * 1000

        summary = self.logger._summarize_result(result)

        self.assertEqual(summary["type"], "string")
        self.assertEqual(summary["length"], 1000)
        self.assertEqual(len(summary["preview"]), 500)

    def test_timed_call_context_manager(self):
        """Should time and log calls via context manager."""
        import time

        with self.logger.timed_call("timed_tool", "system_read", {"x": 1}) as ctx:
            time.sleep(0.01)  # 10ms
            ctx.set_result({"done": True})

        log = MCPAuditLog.objects.get(tool_name="timed_tool")
        self.assertTrue(log.success)
        self.assertGreaterEqual(log.duration_ms, 10)

    def test_timed_call_with_error(self):
        """Should log errors from timed calls."""
        try:
            with self.logger.timed_call("error_tool", "system_read", {}) as _ctx:
                raise ValueError("Test error")
        except ValueError:
            pass

        log = MCPAuditLog.objects.get(tool_name="error_tool")
        self.assertFalse(log.success)
        self.assertIn("Test error", log.error_message)
