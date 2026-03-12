"""
MCP Context tools for setting execution context.

These tools are used to establish the account context for MCP operations.
"""

import logging
from typing import Any

from apps.mcp.tools.base import MCPTool, build_input_schema

logger = logging.getLogger(__name__)


def _resolve_user(end_user_issuer: str | None, end_user_subject: str | None):
    """
    Resolve end user to a Django User based on issuer/subject.

    Returns the User object or None if not found.
    """
    from allauth.socialaccount.models import SocialAccount
    from django.contrib.auth import get_user_model

    User = get_user_model()

    if not end_user_issuer or not end_user_subject:
        return None

    # Try to find by social account (OAuth providers)
    try:
        # Map common issuers to allauth provider names
        provider_map = {
            "https://accounts.google.com": "google",
            "https://login.microsoftonline.com": "microsoft",
            "https://github.com": "github",
        }
        provider = provider_map.get(end_user_issuer)
        if provider:
            social = SocialAccount.objects.get(provider=provider, uid=end_user_subject)
            return social.user
    except SocialAccount.DoesNotExist:
        pass

    # Try direct email match if subject looks like email
    if "@" in end_user_subject:
        try:
            return User.objects.get(email=end_user_subject)
        except User.DoesNotExist:
            pass

    # Try username match
    try:
        return User.objects.get(username=end_user_subject)
    except User.DoesNotExist:
        pass

    return None


async def set_context(
    ctx,
    account_id: str | None = None,
    account_external_id: str | None = None,
    project_id: int | None = None,
    end_user_issuer: str | None = None,
    end_user_subject: str | None = None,
) -> dict[str, Any]:
    """
    Set the execution context for subsequent MCP tool calls.

    This tool establishes:
    - Which account the agent is operating in
    - Project ID for scoping (optional)
    - End user information for audit logging

    Returns the resolved context.
    """
    from apps.accounts.models import Account, AccountUser

    resolved = {
        "account_id": None,
        "account_name": None,
        "project_id": project_id,
        "user_id": None,
        "user_email": None,
        "is_admin": False,
        "end_user_issuer": end_user_issuer,
        "end_user_subject": end_user_subject,
    }

    # Resolve account
    account = None
    if account_id:
        try:
            account = Account.objects.get(id=int(account_id))
            resolved["account_id"] = account.id
            resolved["account_name"] = account.name
        except (Account.DoesNotExist, ValueError):
            logger.warning(f"Account not found: {account_id}")
    elif account_external_id:
        try:
            account = Account.objects.get(external_id=account_external_id)
            resolved["account_id"] = account.id
            resolved["account_name"] = account.name
        except Account.DoesNotExist:
            logger.warning(f"Account not found by external_id: {account_external_id}")

    # Resolve end user and permissions
    user = _resolve_user(end_user_issuer, end_user_subject)
    if user:
        resolved["user_id"] = user.id
        resolved["user_email"] = user.email

        # Check account-level access
        if account:
            try:
                account_user = AccountUser.objects.get(account=account, user=user)
                resolved["is_admin"] = account_user.is_admin
            except AccountUser.DoesNotExist:
                pass

    # Store context in session
    if hasattr(ctx, "session"):
        ctx.session.context = resolved
        ctx.session.account_id = resolved.get("account_id")
        ctx.session.project_id = project_id
        ctx.session.end_user_issuer = end_user_issuer
        ctx.session.end_user_subject = end_user_subject

    return {"success": True, "context": resolved}


async def get_context(ctx) -> dict[str, Any]:
    """
    Get the current execution context.

    Returns account, project, and user information.
    """
    if not hasattr(ctx, "session"):
        return {"error": "No session context. Call set_context first."}

    session = ctx.session
    context = getattr(session, "context", None)

    if not context:
        return {"error": "No context set. Call set_context first."}

    return {
        "success": True,
        "context": context,
    }


def get_context_user(ctx):
    """
    Get the resolved user from context.

    Returns the Django User object or None.
    """
    if not hasattr(ctx, "session"):
        return None
    return getattr(ctx.session, "user", None)


def get_context_tools() -> list[MCPTool]:
    """Get context-related MCP tools."""
    return [
        MCPTool(
            name="set_context",
            description="""Set the execution context for subsequent MCP tool calls.

This tool should be called first to establish:
- account_id or account_external_id: The account to operate in
- project_id: Optional project ID for scoping tools
- end_user_issuer: The identity provider (e.g., "https://auth.example.com")
- end_user_subject: The user identifier from the identity provider

Returns the resolved context with account and user information.""",
            llm_description="Set account context. Call first before other tools.",
            tool_hints="Call this once at the start of your session with account_id or account_external_id.",
            input_schema=build_input_schema(
                properties={
                    "account_id": {"type": "string", "description": "Account ID (numeric)"},
                    "account_external_id": {"type": "string", "description": "External account identifier"},
                    "project_id": {"type": "integer", "description": "Project ID for scoping"},
                    "end_user_issuer": {
                        "type": "string",
                        "description": "Identity provider URL (e.g., https://accounts.google.com)",
                    },
                    "end_user_subject": {
                        "type": "string",
                        "description": "User identifier from identity provider (email or user ID)",
                    },
                },
                required=[],
            ),
            handler=set_context,
            tool_type="context",
            examples=[
                {
                    "description": "Set context with account ID",
                    "input": {"account_id": "123"},
                    "output": {"success": True, "context": {"account_id": 123, "account_name": "Acme Corp"}},
                },
            ],
        ),
        MCPTool(
            name="get_context",
            description="""Get the current execution context.

Returns account, project, and user information that was set with set_context.""",
            llm_description="Get current context.",
            tool_hints="Call after set_context to verify the context.",
            input_schema=build_input_schema(properties={}, required=[]),
            handler=get_context,
            tool_type="context",
            examples=[
                {
                    "description": "Get current context",
                    "input": {},
                    "output": {"success": True, "context": {"account_id": 123, "account_name": "Acme Corp"}},
                }
            ],
        ),
    ]
