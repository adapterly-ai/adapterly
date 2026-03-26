"""Usage counting and plan limit enforcement."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.account import Account, PLAN_LIMITS
from ..models.audit import AuditLog
from ..models.workspace import Workspace
from ..models.connection import Connection
from ..models.account import Member

logger = logging.getLogger(__name__)


async def get_usage(db: AsyncSession, account_id: str) -> dict:
    """Get current usage counters for an account."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return {}

    limits = account.limits

    # Count workspaces
    ws_count = (await db.execute(
        select(func.count(Workspace.id)).where(Workspace.account_id == account_id)
    )).scalar() or 0

    # Count connections across all workspaces
    ws_ids = (await db.execute(
        select(Workspace.id).where(Workspace.account_id == account_id)
    )).scalars().all()
    conn_count = 0
    if ws_ids:
        conn_count = (await db.execute(
            select(func.count(Connection.id)).where(Connection.workspace_id.in_(ws_ids))
        )).scalar() or 0

    # Count members
    member_count = (await db.execute(
        select(func.count(Member.id)).where(Member.account_id == account_id)
    )).scalar() or 0

    # Count tool calls since last reset
    since = account.usage_reset_at or account.created_at
    tool_calls = (await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.account_id == account_id,
            AuditLog.created_at >= since,
        )
    )).scalar() or 0

    return {
        "plan": account.plan,
        "workspaces": {"used": ws_count, "limit": limits["workspaces"]},
        "connections": {"used": conn_count, "limit": limits["connections"]},
        "members": {"used": member_count, "limit": limits["members"]},
        "tool_calls_monthly": {"used": tool_calls, "limit": limits["tool_calls_monthly"]},
        "usage_reset_at": account.usage_reset_at.isoformat() if account.usage_reset_at else None,
    }


async def check_tool_call_limit(db: AsyncSession, account_id: str) -> str | None:
    """Check if account has exceeded tool call limit. Returns error message or None."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return "Account not found"

    limit = account.limits["tool_calls_monthly"]
    if limit == -1:
        return None  # unlimited

    since = account.usage_reset_at or account.created_at
    tool_calls = (await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.account_id == account_id,
            AuditLog.created_at >= since,
        )
    )).scalar() or 0

    if tool_calls >= limit:
        return f"Monthly tool call limit reached ({tool_calls}/{limit}). Upgrade your plan at https://adapterly.ai/billing"

    return None


async def check_workspace_limit(db: AsyncSession, account_id: str) -> str | None:
    """Check if account can create another workspace."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return "Account not found"

    limit = account.limits["workspaces"]
    if limit == -1:
        return None

    count = (await db.execute(
        select(func.count(Workspace.id)).where(Workspace.account_id == account_id)
    )).scalar() or 0

    if count >= limit:
        return f"Workspace limit reached ({count}/{limit}). Upgrade your plan."

    return None


async def check_connection_limit(db: AsyncSession, account_id: str) -> str | None:
    """Check if account can create another connection."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return "Account not found"

    limit = account.limits["connections"]
    if limit == -1:
        return None

    ws_ids = (await db.execute(
        select(Workspace.id).where(Workspace.account_id == account_id)
    )).scalars().all()

    count = 0
    if ws_ids:
        count = (await db.execute(
            select(func.count(Connection.id)).where(Connection.workspace_id.in_(ws_ids))
        )).scalar() or 0

    if count >= limit:
        return f"Connection limit reached ({count}/{limit}). Upgrade your plan."

    return None


async def check_member_limit(db: AsyncSession, account_id: str) -> str | None:
    """Check if account can add another member."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return "Account not found"

    limit = account.limits["members"]
    if limit == -1:
        return None

    count = (await db.execute(
        select(func.count(Member.id)).where(Member.account_id == account_id)
    )).scalar() or 0

    if count >= limit:
        return f"Member limit reached ({count}/{limit}). Upgrade your plan."

    return None
