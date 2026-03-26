"""Standalone setup wizard – creates initial account, workspace, and API key."""

from __future__ import annotations

import logging

from sqlalchemy import select

from ..database import get_session_factory
from ..models.account import Account
from ..models.api_key import APIKey, generate_api_key
from ..models.workspace import Workspace

logger = logging.getLogger(__name__)


async def ensure_standalone_setup() -> str | None:
    """
    In standalone mode, ensure a default account+workspace+API key exist.
    Returns the raw API key if newly created, None if already set up.
    """
    factory = get_session_factory()
    async with factory() as db:
        # Check if any account exists
        result = await db.execute(select(Account).limit(1))
        if result.scalar_one_or_none():
            return None  # Already set up

        # Create default account
        account = Account(name="Default", slug="default")
        db.add(account)
        await db.flush()

        # Create default workspace
        workspace = Workspace(
            account_id=account.id,
            name="Default Workspace",
            slug="default",
        )
        db.add(workspace)
        await db.flush()

        # Create admin API key
        raw_key, prefix, key_hash = generate_api_key()
        api_key = APIKey(
            account_id=account.id,
            workspace_id=workspace.id,
            name="Default Admin Key",
            key_prefix=prefix,
            key_hash=key_hash,
            mode="power",
            is_admin=True,
        )
        db.add(api_key)
        await db.commit()

        logger.info(f"Standalone setup complete. API key: {raw_key}")
        return raw_key
