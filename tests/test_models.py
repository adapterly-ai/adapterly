"""Tests for SQLAlchemy models: creation, defaults, nanoid, hash."""

from __future__ import annotations

import hashlib
import re

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adapterly.models import (
    Account,
    APIKey,
    AuditLog,
    Connection,
    Integration,
    Tool,
    Workspace,
)
from adapterly.models.api_key import KEY_PREFIX, generate_api_key
from adapterly.models.base import generate_id


# ── nanoid generation ─────────────────────────────────────────────────────

class TestNanoid:
    def test_generate_id_length(self):
        nid = generate_id()
        assert len(nid) == 21

    def test_generate_id_uniqueness(self):
        ids = {generate_id() for _ in range(200)}
        assert len(ids) == 200

    def test_generate_id_is_string(self):
        assert isinstance(generate_id(), str)


# ── API key generation ────────────────────────────────────────────────────

class TestAPIKeyGeneration:
    def test_generate_api_key_returns_triple(self):
        full_key, prefix, key_hash = generate_api_key()
        assert isinstance(full_key, str)
        assert isinstance(prefix, str)
        assert isinstance(key_hash, str)

    def test_full_key_has_prefix(self):
        full_key, _, _ = generate_api_key()
        assert full_key.startswith(KEY_PREFIX)

    def test_prefix_is_first_12_chars(self):
        full_key, prefix, _ = generate_api_key()
        assert prefix == full_key[:12]

    def test_hash_matches(self):
        full_key, _, key_hash = generate_api_key()
        expected = hashlib.sha256(full_key.encode()).hexdigest()
        assert key_hash == expected

    def test_hash_key_static_method(self):
        raw = "ak_abcdefghijklmnop"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert APIKey.hash_key(raw) == expected


# ── Model creation (DB round-trip) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_account(db: AsyncSession):
    account = Account(name="Acme Corp", slug="acme")
    db.add(account)
    await db.commit()
    await db.refresh(account)

    assert len(account.id) == 21
    assert account.name == "Acme Corp"
    assert account.slug == "acme"
    assert account.is_active is True
    assert account.created_at is not None
    assert account.updated_at is not None


@pytest.mark.asyncio
async def test_create_workspace(db: AsyncSession, test_account: Account):
    ws = Workspace(
        account_id=test_account.id,
        name="Staging",
        slug="staging",
        description="Staging env",
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)

    assert len(ws.id) == 21
    assert ws.account_id == test_account.id
    assert ws.slug == "staging"
    assert ws.is_active is True


@pytest.mark.asyncio
async def test_create_integration_with_tools(db: AsyncSession, test_integration: Integration):
    result = await db.execute(
        select(Tool).where(Tool.integration_id == test_integration.id)
    )
    tools = result.scalars().all()
    assert len(tools) == 2
    slugs = {t.slug for t in tools}
    assert "list_items" in slugs
    assert "create_item" in slugs

    for tool in tools:
        assert len(tool.id) == 21
        assert tool.integration_id == test_integration.id


@pytest.mark.asyncio
async def test_tool_defaults(db: AsyncSession, test_integration: Integration):
    tool = Tool(
        integration_id=test_integration.id,
        slug="minimal",
        name="Minimal Tool",
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)

    assert tool.method == "GET"
    assert tool.path == ""
    assert tool.tool_type == "read"
    assert tool.is_enabled is True
    assert tool.headers == {}
    assert tool.parameters_schema == {}


@pytest.mark.asyncio
async def test_create_connection(
    db: AsyncSession,
    test_workspace: Workspace,
    test_integration: Integration,
):
    conn = Connection(
        workspace_id=test_workspace.id,
        integration_id=test_integration.id,
        credentials={"token": "encrypted-token-here"},
        external_id="project-123",
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    assert len(conn.id) == 21
    assert conn.workspace_id == test_workspace.id
    assert conn.is_enabled is True
    assert conn.is_verified is False
    assert conn.last_error is None
    assert conn.credentials["token"] == "encrypted-token-here"


@pytest.mark.asyncio
async def test_create_api_key(db: AsyncSession, test_account: Account):
    full_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(
        account_id=test_account.id,
        name="CI Key",
        key_prefix=prefix,
        key_hash=key_hash,
        mode="safe",
        is_admin=False,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    assert len(api_key.id) == 21
    assert api_key.key_prefix == prefix
    assert api_key.mode == "safe"
    assert api_key.is_admin is False
    assert api_key.is_active is True
    assert api_key.allowed_tools == []
    assert api_key.blocked_tools == []


@pytest.mark.asyncio
async def test_create_audit_log(db: AsyncSession, test_account: Account):
    log = AuditLog(
        account_id=test_account.id,
        workspace_id=None,
        api_key_id=None,
        tool_name="test_tool",
        parameters={"key": "value"},
        duration_ms=42.5,
        success=True,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    assert len(log.id) == 21
    assert log.tool_name == "test_tool"
    assert log.duration_ms == 42.5
    assert log.success is True
    assert log.error_message is None
    assert log.status_code is None
    assert log.created_at is not None


@pytest.mark.asyncio
async def test_account_default_id_generated(db: AsyncSession):
    """ID should be auto-generated via generate_id default."""
    a1 = Account(name="A", slug="a")
    a2 = Account(name="B", slug="b")
    db.add_all([a1, a2])
    await db.commit()
    await db.refresh(a1)
    await db.refresh(a2)
    assert a1.id != a2.id
    assert len(a1.id) == 21
