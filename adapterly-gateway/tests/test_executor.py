"""Tests for gateway_core.executor — tool generation helpers."""

from dataclasses import dataclass
from typing import Any

import pytest

from gateway_core.executor import (
    _action_to_tool,
    _build_action_input_schema,
    _sanitize_tool_name,
    get_system_tools,
)

from .conftest import create_test_data

# ---------------------------------------------------------------------------
# Lightweight stubs for pure-function tests (no SQLAlchemy session needed)
# ---------------------------------------------------------------------------


@dataclass
class _StubSystem:
    alias: str = "testsys"
    display_name: str = "Test System"


@dataclass
class _StubInterface:
    alias: str = "testapi"
    name: str = "Test API"
    type: str = "API"
    system: Any = None


@dataclass
class _StubResource:
    alias: str = "users"
    name: str = "Users"
    interface: Any = None


@dataclass
class _StubAction:
    id: int = 1
    alias: str = "list"
    name: str = "List Users"
    description: str = "Test action"
    method: str = "GET"
    path: str = "/api/users"
    parameters_schema: dict | None = None
    pagination: dict | None = None
    resource: Any = None


def _make_action_stub(
    method="GET",
    alias="list",
    interface_type="API",
    action_name="List Users",
    description="Test action",
    path="/api/users",
    parameters_schema=None,
    pagination=None,
) -> _StubAction:
    system = _StubSystem()
    interface = _StubInterface(type=interface_type, system=system)
    resource = _StubResource(interface=interface)
    return _StubAction(
        alias=alias,
        name=action_name,
        description=description,
        method=method,
        path=path,
        parameters_schema=parameters_schema,
        pagination=pagination,
        resource=resource,
    )


# ---------------------------------------------------------------------------
# _sanitize_tool_name
# ---------------------------------------------------------------------------


class TestSanitizeToolName:
    def test_basic(self):
        assert _sanitize_tool_name("hello_world") == "hello_world"

    def test_special_characters(self):
        assert _sanitize_tool_name("user-list.v2") == "user_list_v2"

    def test_multiple_underscores(self):
        assert _sanitize_tool_name("foo___bar") == "foo_bar"

    def test_leading_trailing_underscores(self):
        assert _sanitize_tool_name("__foo__") == "foo"

    def test_uppercase_to_lowercase(self):
        assert _sanitize_tool_name("FooBar") == "foobar"

    def test_combined(self):
        assert _sanitize_tool_name("My--System.Users/List") == "my_system_users_list"

    def test_empty_string(self):
        assert _sanitize_tool_name("") == ""


# ---------------------------------------------------------------------------
# _build_action_input_schema
# ---------------------------------------------------------------------------


class TestBuildActionInputSchema:
    def test_with_parameters_schema(self):
        action = _make_action_stub(
            parameters_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
            }
        )
        schema = _build_action_input_schema(action)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]

    def test_with_parameters_schema_and_pagination(self):
        action = _make_action_stub(
            parameters_schema={
                "type": "object",
                "properties": {"filter": {"type": "string"}},
            },
            pagination={"page_param": "page"},
        )
        schema = _build_action_input_schema(action)
        assert "page" in schema["properties"]
        assert "fetch_all_pages" in schema["properties"]
        assert "filter" in schema["properties"]

    def test_graphql_schema(self):
        action = _make_action_stub()
        schema = _build_action_input_schema(action, interface_type="GRAPHQL")
        assert schema["required"] == ["query"]
        assert "query" in schema["properties"]
        assert "variables" in schema["properties"]
        assert "operation_name" in schema["properties"]

    def test_rest_path_params(self):
        action = _make_action_stub(path="/api/users/{user_id}/posts/{post_id}", method="GET")
        schema = _build_action_input_schema(action)
        assert "user_id" in schema["properties"]
        assert "post_id" in schema["properties"]
        assert set(schema["required"]) == {"user_id", "post_id"}

    def test_post_includes_data(self):
        action = _make_action_stub(path="/api/users", method="POST")
        schema = _build_action_input_schema(action)
        assert "data" in schema["properties"]

    def test_get_no_data(self):
        action = _make_action_stub(path="/api/users", method="GET")
        schema = _build_action_input_schema(action)
        assert "data" not in schema["properties"]

    def test_empty_no_schema(self):
        action = _make_action_stub(path="/api/simple", method="GET")
        schema = _build_action_input_schema(action)
        assert schema["type"] == "object"
        assert schema["properties"] == {}

    def test_schema_without_type_gets_object(self):
        action = _make_action_stub(parameters_schema={"properties": {"x": {"type": "integer"}}})
        schema = _build_action_input_schema(action)
        assert schema["type"] == "object"


# ---------------------------------------------------------------------------
# _action_to_tool
# ---------------------------------------------------------------------------


class TestActionToTool:
    def test_get_is_system_read(self):
        action = _make_action_stub(method="GET")
        tool = _action_to_tool(action)
        assert tool is not None
        assert tool["tool_type"] == "system_read"

    def test_post_is_system_write(self):
        action = _make_action_stub(method="POST", alias="create")
        tool = _action_to_tool(action)
        assert tool["tool_type"] == "system_write"

    def test_tool_name_format(self):
        action = _make_action_stub()
        tool = _action_to_tool(action)
        assert tool["name"] == "testsys_users_list"

    def test_graphql_read(self):
        action = _make_action_stub(method="POST", alias="get_projects", interface_type="GRAPHQL")
        tool = _action_to_tool(action)
        assert tool["tool_type"] == "system_read"

    def test_graphql_mutation_write(self):
        action = _make_action_stub(method="POST", alias="create_project", interface_type="GRAPHQL")
        tool = _action_to_tool(action)
        assert tool["tool_type"] == "system_write"

    def test_pagination_hint_in_description(self):
        action = _make_action_stub(pagination={"page_param": "page"})
        tool = _action_to_tool(action)
        assert "paginated" in tool["description"]


# ---------------------------------------------------------------------------
# get_system_tools (async, needs DB)
# ---------------------------------------------------------------------------


class TestGetSystemTools:
    @pytest.mark.asyncio
    async def test_none_project_returns_empty(self, db):
        await create_test_data(db)
        tools = await get_system_tools(db, account_id=1, project_id=None)
        assert tools == []

    @pytest.mark.asyncio
    async def test_project_scoped_tools(self, db):
        await create_test_data(db)
        tools = await get_system_tools(db, account_id=1, project_id=1)
        # action_read and action_write are mcp_enabled, action_disabled is not
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "testsys_users_list" in names
        assert "testsys_users_create" in names

    @pytest.mark.asyncio
    async def test_no_integration_returns_empty(self, db):
        await create_test_data(db)
        # project_id=999 has no integration
        tools = await get_system_tools(db, account_id=1, project_id=999)
        assert tools == []
