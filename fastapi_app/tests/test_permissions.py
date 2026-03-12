"""Tests for MCPPermissionChecker."""

import pytest
import pytest_asyncio

from fastapi_app.mcp.permissions import MCPPermissionChecker

from .conftest import create_test_data


class TestMCPPermissionCheckerDirect:
    """Unit tests on MCPPermissionChecker — no DB needed for most."""

    def test_admin_blocks_system_read(self):
        checker = MCPPermissionChecker(account_id=1, is_admin=True, mode="safe")
        assert checker.is_tool_allowed("testsys_users_list", "system_read") is False

    def test_admin_blocks_system_write(self):
        checker = MCPPermissionChecker(account_id=1, is_admin=True, mode="power")
        assert checker.is_tool_allowed("testsys_users_create", "system_write") is False

    def test_admin_allows_context(self):
        checker = MCPPermissionChecker(account_id=1, is_admin=True, mode="safe")
        assert checker.is_tool_allowed("get_context", "context") is True

    def test_admin_allows_management(self):
        checker = MCPPermissionChecker(account_id=1, is_admin=True, mode="safe")
        assert checker.is_tool_allowed("manage_keys", "management") is True

    def test_safe_allows_system_read(self):
        checker = MCPPermissionChecker(account_id=1, mode="safe")
        assert checker.is_tool_allowed("testsys_users_list", "system_read") is True

    def test_safe_blocks_system_write(self):
        checker = MCPPermissionChecker(account_id=1, mode="safe")
        assert checker.is_tool_allowed("testsys_users_create", "system_write") is False

    def test_power_allows_system_write(self):
        checker = MCPPermissionChecker(account_id=1, mode="power")
        assert checker.is_tool_allowed("testsys_users_create", "system_write") is True

    def test_allowed_tools_whitelist(self):
        checker = MCPPermissionChecker(account_id=1, mode="power", allowed_tools=["foo"])
        assert checker.is_tool_allowed("foo", "system_read") is True
        assert checker.is_tool_allowed("bar", "system_read") is False

    def test_non_system_always_allowed(self):
        checker = MCPPermissionChecker(account_id=1, mode="safe")
        assert checker.is_tool_allowed("any_resource", "resource") is True
        assert checker.is_tool_allowed("any_dataset", "dataset") is True

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            MCPPermissionChecker(account_id=1, mode="xxx")


@pytest.mark.asyncio
class TestMCPPermissionCheckerCreate:
    """Test the async create() factory method with DB."""

    async def test_create_from_db(self, db):
        data = await create_test_data(db)
        checker = await MCPPermissionChecker.create(
            account_id=1,
            api_key_id=data["api_key"].id,
            is_admin=False,
            db=db,
        )
        # Should load mode from API key (safe)
        assert checker.mode == "safe"
        assert checker.is_admin is False

    async def test_create_admin_from_db(self, db):
        data = await create_test_data(db)
        checker = await MCPPermissionChecker.create(
            account_id=1,
            api_key_id=data["admin_key"].id,
            is_admin=True,
            db=db,
        )
        assert checker.is_admin is True
