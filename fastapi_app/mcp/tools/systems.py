"""
MCP System Tools - Auto-generated from Action definitions.

These tools provide direct access to integrated systems:
- Read operations (system_read): List, get, search
- Write operations (system_write): Create, update, delete

Tool names follow the pattern: {system}_{resource}_{action}
Example: salesforce_contact_create, hubspot_deal_update

Implementation delegated to gateway_core.executor.
"""

# Re-export from gateway_core — this is the single integration point.
# All execution logic lives in gateway_core.executor so it can be used
# by both the monolith FastAPI app and standalone gateway deployments.
from gateway_core.executor import (  # noqa: F401
    _action_to_tool,
    _build_action_input_schema,
    _confirm_system_if_needed,
    _detect_token_expiry,
    _execute_graphql,
    _execute_read,
    _execute_write,
    _extract_items_from_response,
    _get_auth_headers,
    _get_drf_token,
    _get_oauth_token,
    _inject_project_filter,
    _sanitize_tool_name,
    _substitute_path_params,
    execute_system_tool,
    get_system_tools,
)
