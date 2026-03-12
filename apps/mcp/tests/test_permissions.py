"""
Tests for MCP permission system.
"""

from django.test import TestCase

from apps.mcp.permissions import MCPPermissionChecker


class TestMCPPermissionChecker(TestCase):
    """Tests for MCPPermissionChecker."""

    def test_safe_mode_allows_system_read_tools(self):
        """Safe mode should allow system read tools."""
        checker = MCPPermissionChecker(account_id=1, mode="safe")

        result = checker.can_call_tool("salesforce_contact_list", "system_read")

        self.assertTrue(result.allowed)

    def test_safe_mode_allows_system_read(self):
        """Safe mode should allow system read operations."""
        checker = MCPPermissionChecker(account_id=1, mode="safe")

        result = checker.can_call_tool("salesforce_contact_list", "system_read")

        self.assertTrue(result.allowed)

    def test_safe_mode_denies_system_write(self):
        """Safe mode should deny system write operations."""
        checker = MCPPermissionChecker(account_id=1, mode="safe")

        result = checker.can_call_tool("salesforce_contact_create", "system_write")

        self.assertFalse(result.allowed)
        self.assertIn("safe", result.reason.lower())

    def test_power_mode_allows_system_write(self):
        """Power mode should allow system write operations."""
        checker = MCPPermissionChecker(account_id=1, mode="power")

        result = checker.can_call_tool("salesforce_contact_create", "system_write")

        self.assertTrue(result.allowed)

    def test_blocked_tools_are_denied(self):
        """Blocked tools should be denied in any mode."""
        checker = MCPPermissionChecker(account_id=1, mode="power", blocked_tools=["salesforce_*_delete"])

        result = checker.can_call_tool("salesforce_contact_delete", "system_write")

        self.assertFalse(result.allowed)
        self.assertIn("blocked", result.reason.lower())

    def test_allowed_tools_filter(self):
        """Allowed tools pattern should filter tools."""
        checker = MCPPermissionChecker(account_id=1, mode="power", allowed_tools=["hubspot_*"])

        # HubSpot tool should be allowed
        result_allowed = checker.can_call_tool("hubspot_deal_update", "system_write")
        self.assertTrue(result_allowed.allowed)

        # Salesforce tool should be denied
        result_denied = checker.can_call_tool("salesforce_contact_create", "system_write")
        self.assertFalse(result_denied.allowed)

    def test_resource_access_always_allowed(self):
        """Resource access should always be allowed."""
        checker = MCPPermissionChecker(account_id=1, mode="safe")

        result = checker.can_call_tool("systems://salesforce", "resource")

        self.assertTrue(result.allowed)

    def test_invalid_mode_raises_error(self):
        """Invalid mode should raise ValueError."""
        with self.assertRaises(ValueError):
            MCPPermissionChecker(account_id=1, mode="invalid")

    def test_get_tool_list_filter_safe_mode(self):
        """Safe mode filter should exclude write tools."""
        checker = MCPPermissionChecker(account_id=1, mode="safe")

        filter_opts = checker.get_tool_list_filter()

        self.assertFalse(filter_opts["include_write"])

    def test_get_tool_list_filter_power_mode(self):
        """Power mode filter should include write tools."""
        checker = MCPPermissionChecker(account_id=1, mode="power")

        filter_opts = checker.get_tool_list_filter()

        self.assertTrue(filter_opts["include_write"])
