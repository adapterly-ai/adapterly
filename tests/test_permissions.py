"""Tests for adapterly.mcp.permissions.PermissionChecker."""

from __future__ import annotations

import pytest

from adapterly.mcp.permissions import PermissionChecker


class TestSafeMode:
    """In safe mode, write tools are blocked."""

    def test_safe_blocks_write(self):
        checker = PermissionChecker(mode="safe")
        assert checker.is_allowed("some_tool", "write") is False

    def test_safe_allows_read(self):
        checker = PermissionChecker(mode="safe")
        assert checker.is_allowed("some_tool", "read") is True

    def test_safe_is_case_insensitive(self):
        checker = PermissionChecker(mode="Safe")
        assert checker.is_allowed("tool", "write") is False
        assert checker.is_allowed("tool", "read") is True


class TestPowerMode:
    """In power mode, all tool types are allowed."""

    def test_power_allows_write(self):
        checker = PermissionChecker(mode="power")
        assert checker.is_allowed("any_tool", "write") is True

    def test_power_allows_read(self):
        checker = PermissionChecker(mode="power")
        assert checker.is_allowed("any_tool", "read") is True


class TestWhitelist:
    """When allowed_tools is non-empty, only those tools are visible."""

    def test_whitelist_allows_listed_tool(self):
        checker = PermissionChecker(
            mode="power",
            allowed_tools=["tool_a", "tool_b"],
        )
        assert checker.is_allowed("tool_a", "read") is True
        assert checker.is_allowed("tool_b", "write") is True

    def test_whitelist_blocks_unlisted_tool(self):
        checker = PermissionChecker(
            mode="power",
            allowed_tools=["tool_a"],
        )
        assert checker.is_allowed("tool_c", "read") is False

    def test_empty_whitelist_means_all_allowed(self):
        checker = PermissionChecker(mode="power", allowed_tools=[])
        assert checker.is_allowed("any_tool", "read") is True

    def test_none_whitelist_means_all_allowed(self):
        checker = PermissionChecker(mode="power", allowed_tools=None)
        assert checker.is_allowed("any_tool", "read") is True


class TestBlacklist:
    """Blacklisted tools are always hidden, regardless of mode or whitelist."""

    def test_blacklist_blocks_in_power_mode(self):
        checker = PermissionChecker(
            mode="power",
            blocked_tools=["dangerous_tool"],
        )
        assert checker.is_allowed("dangerous_tool", "read") is False

    def test_blacklist_blocks_even_if_whitelisted(self):
        checker = PermissionChecker(
            mode="power",
            allowed_tools=["tool_x"],
            blocked_tools=["tool_x"],
        )
        assert checker.is_allowed("tool_x", "read") is False

    def test_non_blacklisted_tool_passes(self):
        checker = PermissionChecker(
            mode="power",
            blocked_tools=["bad_tool"],
        )
        assert checker.is_allowed("good_tool", "read") is True

    def test_empty_blacklist_blocks_nothing(self):
        checker = PermissionChecker(mode="power", blocked_tools=[])
        assert checker.is_allowed("any_tool", "read") is True


class TestCombinedRules:
    """Interaction between mode, whitelist, and blacklist."""

    def test_safe_mode_with_whitelist(self):
        checker = PermissionChecker(
            mode="safe",
            allowed_tools=["read_tool", "write_tool"],
        )
        assert checker.is_allowed("read_tool", "read") is True
        # write blocked by safe mode even though whitelisted
        assert checker.is_allowed("write_tool", "write") is False

    def test_safe_mode_with_blacklist(self):
        checker = PermissionChecker(
            mode="safe",
            blocked_tools=["read_tool"],
        )
        assert checker.is_allowed("read_tool", "read") is False
        assert checker.is_allowed("other_tool", "read") is True

    def test_power_whitelist_and_blacklist(self):
        checker = PermissionChecker(
            mode="power",
            allowed_tools=["a", "b", "c"],
            blocked_tools=["b"],
        )
        assert checker.is_allowed("a", "write") is True
        assert checker.is_allowed("b", "read") is False  # blacklisted
        assert checker.is_allowed("c", "write") is True
        assert checker.is_allowed("d", "read") is False  # not whitelisted

    def test_defaults_are_safe_no_lists(self):
        checker = PermissionChecker()
        assert checker.mode == "safe"
        assert checker.allowed_tools == set()
        assert checker.blocked_tools == set()
        assert checker.is_allowed("tool", "read") is True
        assert checker.is_allowed("tool", "write") is False
