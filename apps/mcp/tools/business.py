"""
MCP Business Tools - Generated from CapabilityPacks.

These tools provide business-level semantic abstractions over raw API endpoints.
For example:
  - create_sales_lead instead of salesforce_contact_create
  - list_active_customers instead of GET /accounts?status=active

Business tools include:
- Simplified, domain-specific parameters
- Sensible defaults
- Field mapping between business concepts and API fields
- LLM-optimized descriptions
"""

import logging
from typing import Any

from asgiref.sync import sync_to_async

from apps.mcp.tools.base import MCPTool

logger = logging.getLogger(__name__)


def get_business_tools(account_id: int) -> list[MCPTool]:
    """
    Generate MCP tools from BusinessTool definitions for an account.

    Args:
        account_id: Account ID to generate tools for

    Returns:
        List of MCPTool objects representing business-level operations
    """
    from apps.mcp.models import CapabilityPack

    tools = []

    try:
        # Get all active packs for this account (account-specific + global)
        packs = list(
            CapabilityPack.objects.filter(
                models.Q(account_id=account_id) | models.Q(is_global=True), is_active=True
            ).prefetch_related("business_tools")
        )

        for pack in packs:
            # Check if required systems are enabled for this account
            if pack.requires_systems:
                if not _check_required_systems(account_id, pack.requires_systems):
                    logger.debug(f"Skipping pack {pack.alias}: required systems not enabled")
                    continue

            # Generate tools from this pack
            for business_tool in pack.business_tools.filter(is_active=True):
                tool = _business_tool_to_mcp_tool(business_tool, account_id)
                if tool:
                    tools.append(tool)

        logger.info(f"Generated {len(tools)} business tools for account {account_id}")

    except Exception as e:
        logger.warning(f"Error generating business tools: {e}")

    return tools


def _check_required_systems(account_id: int, required_systems: list[str]) -> bool:
    """Check if all required systems are enabled for the account."""
    from apps.systems.models import AccountSystem

    enabled_systems = set(
        AccountSystem.objects.filter(account_id=account_id, is_enabled=True).values_list("system__alias", flat=True)
    )

    return all(sys in enabled_systems for sys in required_systems)


def _business_tool_to_mcp_tool(business_tool, account_id: int) -> MCPTool | None:
    """
    Convert a BusinessTool to an MCPTool.

    Args:
        business_tool: BusinessTool model instance
        account_id: Account ID for context

    Returns:
        MCPTool or None if conversion fails
    """
    try:
        pack = business_tool.pack

        # Build namespaced tool name: pack_alias:tool_name
        tool_name = f"{pack.alias}_{business_tool.name}"

        # Determine tool type
        tool_type = business_tool.get_mcp_tool_type()

        # Build input schema with business-level parameters
        input_schema = business_tool.input_schema.copy() if business_tool.input_schema else {}
        if "type" not in input_schema:
            input_schema["type"] = "object"
        if "properties" not in input_schema:
            input_schema["properties"] = {}

        # Create handler function
        handler = _create_business_tool_handler(
            business_tool_id=business_tool.id,
            maps_to_system=business_tool.maps_to_system,
            maps_to_action=business_tool.maps_to_action,
        )

        # Build description
        description = business_tool.description
        llm_description = business_tool.llm_description or description

        return MCPTool(
            name=tool_name,
            description=description,
            llm_description=llm_description,
            tool_hints=business_tool.tool_hints or None,
            input_schema=input_schema,
            handler=handler,
            tool_type=tool_type,
            output_schema=business_tool.output_schema or None,
            examples=business_tool.examples or [],
        )

    except Exception as e:
        logger.error(f"Failed to convert business tool {business_tool}: {e}")
        return None


def _create_business_tool_handler(business_tool_id: int, maps_to_system: str, maps_to_action: str):
    """
    Create a handler function for a business tool.

    The handler:
    1. Loads the BusinessTool definition
    2. Transforms business-level input to API-level input
    3. Executes the underlying system action
    4. Transforms API response to business-level output
    """

    async def handler(ctx: dict[str, Any], **params) -> dict[str, Any]:
        """Execute the business tool."""
        from apps.mcp.models import BusinessTool
        from apps.systems.models import AccountSystem, Action

        account_id = ctx["account_id"]
        _session_manager = ctx.get("session_manager")

        try:
            # Load the business tool definition
            @sync_to_async
            def get_business_tool():
                return BusinessTool.objects.select_related("pack").get(id=business_tool_id)

            business_tool = await get_business_tool()

            # Transform business input to API input
            api_params = business_tool.transform_input(params)

            # Find the underlying action
            @sync_to_async
            def find_action():
                # Parse the action reference
                action_parts = maps_to_action.split(".")
                if len(action_parts) == 1:
                    # Simple action name
                    action_alias = action_parts[0]
                else:
                    # interface.resource.action format
                    action_alias = action_parts[-1]

                return (
                    Action.objects.select_related("resource__interface__system")
                    .filter(resource__interface__system__alias=maps_to_system, alias__icontains=action_alias)
                    .first()
                )

            action = await find_action()

            if not action:
                return {"error": f"Underlying action not found: {maps_to_system}/{maps_to_action}"}

            # Get authentication
            @sync_to_async
            def get_auth():
                try:
                    account_system = AccountSystem.objects.get(
                        account_id=account_id, system__alias=maps_to_system, is_enabled=True
                    )
                    return account_system.get_auth_headers()
                except AccountSystem.DoesNotExist:
                    return None

            auth_headers = await get_auth()

            if not auth_headers:
                return {"error": f"System {maps_to_system} not configured for this account"}

            # Execute the action (reusing existing system tool logic)
            from apps.mcp.tools.systems import _execute_read, _execute_write, _substitute_path_params

            interface = action.resource.interface
            method = action.method.upper()

            # Build URL
            path = _substitute_path_params(action.path or "", api_params)
            url = f"{interface.base_url.rstrip('/')}/{path.lstrip('/')}"

            # Extract body data for write operations
            data = api_params.pop("data", None)

            # Execute based on method
            if method in ("GET", "HEAD", "OPTIONS"):
                result = await _execute_read(
                    url=url,
                    method=method,
                    params=api_params,
                    headers={**(action.headers or {}), **auth_headers},
                    action=action,
                )
            else:
                result = await _execute_write(
                    url=url,
                    method=method,
                    data=data or api_params,
                    headers={**(action.headers or {}), **auth_headers},
                    action=action,
                )

            # Transform output if mapping defined
            if result.get("success") and result.get("data"):
                result["data"] = business_tool.transform_output(result["data"])

            # Add business context to result
            result["business_tool"] = business_tool.name
            result["pack"] = business_tool.pack.alias

            return result

        except Exception as e:
            logger.error(f"Business tool execution failed: {e}")
            return {"error": str(e)}

    return handler


# Need to import models for the Q filter
from django.db import models  # noqa: E402


def refresh_business_tools(registry, account_id: int):
    """
    Refresh business tools in the registry.

    Call this when capability packs or business tools are modified.
    """
    # Remove existing business tools (they have pack prefix)
    from apps.mcp.models import CapabilityPack

    pack_aliases = list(
        CapabilityPack.objects.filter(models.Q(account_id=account_id) | models.Q(is_global=True)).values_list(
            "alias", flat=True
        )
    )

    to_remove = [name for name in registry._tools.keys() if any(name.startswith(f"{alias}_") for alias in pack_aliases)]
    for name in to_remove:
        registry.unregister(name)

    # Add fresh tools
    for tool in get_business_tools(account_id):
        registry.register(tool)

    logger.info(f"Refreshed business tools for account {account_id}")
