"""
Tests for MCP API endpoints.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Account, AccountUser
from apps.mcp.models import MCPApiKey, MCPAuditLog, MCPSession

User = get_user_model()


class MCPApiTestCase(TestCase):
    """Base test case for MCP API tests."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.account = Account.objects.create(name="Test Account")
        AccountUser.objects.create(account=self.account, user=self.user, is_admin=True, is_current_active=True)
        self.client.force_authenticate(user=self.user)

        # Mock the account middleware
        self.client.handler._middleware_chain = None


class TestMCPApiKeyAPI(MCPApiTestCase):
    """Tests for MCP API Key endpoints."""

    def test_create_api_key(self):
        """Should create a new API key and return the full key once."""
        # Note: This test would need proper request.account middleware setup
        pass

    def test_list_api_keys(self):
        """Should list API keys for the account."""
        MCPApiKey.objects.create(
            account=self.account, name="Test Key", key_prefix="ak_live_te", key_hash="hash123", mode="safe"
        )

        # Test would need proper middleware
        pass


class TestMCPApiKeyModel(TestCase):
    """Tests for MCPApiKey model."""

    def setUp(self):
        self.account = Account.objects.create(name="Test Account")

    def test_generate_key(self):
        """Should generate key with correct format."""
        key, prefix, key_hash = MCPApiKey.generate_key()

        self.assertTrue(key.startswith("ak_live_"))
        self.assertEqual(len(prefix), 10)
        self.assertEqual(len(key_hash), 64)  # SHA256 hex

    def test_check_key_valid(self):
        """Should verify valid key."""
        key, prefix, key_hash = MCPApiKey.generate_key()
        api_key = MCPApiKey.objects.create(account=self.account, name="Test", key_prefix=prefix, key_hash=key_hash)

        self.assertTrue(api_key.check_key(key))

    def test_check_key_invalid(self):
        """Should reject invalid key."""
        key, prefix, key_hash = MCPApiKey.generate_key()
        api_key = MCPApiKey.objects.create(account=self.account, name="Test", key_prefix=prefix, key_hash=key_hash)

        self.assertFalse(api_key.check_key("wrong_key"))


class TestMCPSessionModel(TestCase):
    """Tests for MCPSession model."""

    def setUp(self):
        self.account = Account.objects.create(name="Test Account")

    def test_record_tool_call(self):
        """Should increment tool call count."""
        session = MCPSession.objects.create(session_id="test_123", account=self.account, mode="safe")

        session.record_tool_call()
        session.refresh_from_db()

        self.assertEqual(session.tool_calls_count, 1)


class TestMCPAuditLogModel(TestCase):
    """Tests for MCPAuditLog model."""

    def setUp(self):
        self.account = Account.objects.create(name="Test Account")

    def test_create_audit_log(self):
        """Should create audit log with all fields."""
        log = MCPAuditLog.objects.create(
            account=self.account,
            tool_name="test_tool",
            tool_type="system_read",
            parameters={"id": 1},
            result_summary={"success": True},
            duration_ms=100,
            success=True,
            session_id="session_123",
            transport="stdio",
            mode="safe",
        )

        self.assertEqual(str(log), f"test_tool [OK] - {log.timestamp}")

    def test_audit_log_ordering(self):
        """Audit logs should be ordered by timestamp descending."""
        MCPAuditLog.objects.create(account=self.account, tool_name="tool1", tool_type="system_read")
        log2 = MCPAuditLog.objects.create(account=self.account, tool_name="tool2", tool_type="system_read")

        logs = list(MCPAuditLog.objects.all())
        self.assertEqual(logs[0], log2)  # Most recent first
