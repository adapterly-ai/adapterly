"""Shared test fixtures for Adapterly v2."""

from __future__ import annotations

import hashlib
import os
import secrets

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Configure environment BEFORE any app imports ──────────────────────────
os.environ["ADAPTERLY_DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["ADAPTERLY_SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ADAPTERLY_LOAD_CATALOG"] = "false"
os.environ["ADAPTERLY_MODE"] = "standalone"

from adapterly.config import Settings, get_settings  # noqa: E402
from adapterly.crypto import configure_secret_key  # noqa: E402
from adapterly.database import get_db  # noqa: E402
from adapterly.main import create_app  # noqa: E402
from adapterly.models import (  # noqa: E402
    Account,
    APIKey,
    AuditLog,
    Base,
    Connection,
    Integration,
    Member,
    Tool,
    Workspace,
)
from adapterly.models.api_key import KEY_PREFIX  # noqa: E402
from adapterly.models.base import generate_id  # noqa: E402


# ── Async engine for in-memory SQLite ────────────────────────────────────

@pytest_asyncio.fixture()
async def engine():
    """Create a fresh async engine per test (in-memory SQLite)."""
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture()
async def db(engine):
    """Yield an async session bound to the test engine."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── Domain-object fixtures ────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def test_account(db: AsyncSession) -> Account:
    """Create and return a test Account."""
    account = Account(name="Test Org", slug="test-org", plan="self_hosted")
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest_asyncio.fixture()
async def test_workspace(db: AsyncSession, test_account: Account) -> Workspace:
    """Create and return a test Workspace."""
    ws = Workspace(
        account_id=test_account.id,
        name="Default Workspace",
        slug="default",
        description="Workspace for testing",
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


@pytest_asyncio.fixture()
async def test_api_key(
    db: AsyncSession,
    test_account: Account,
    test_workspace: Workspace,
) -> tuple[APIKey, str]:
    """Create a test API key.  Returns (APIKey model, raw_key)."""
    raw = secrets.token_urlsafe(32)
    full_key = f"{KEY_PREFIX}{raw}"
    prefix = full_key[:12]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()

    api_key = APIKey(
        account_id=test_account.id,
        workspace_id=test_workspace.id,
        name="Test Key",
        key_prefix=prefix,
        key_hash=key_hash,
        mode="power",
        is_admin=True,
        allowed_tools=[],
        blocked_tools=[],
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, full_key


@pytest_asyncio.fixture()
async def test_integration(db: AsyncSession, test_account: Account) -> Integration:
    """Create a test Integration with two tools."""
    integration = Integration(
        slug="test-api",
        name="Test API",
        description="Integration for testing",
        category="testing",
        base_url="https://api.example.com",
        auth_config={"type": "bearer"},
        variables={},
        scope="private",
        account_id=test_account.id,
    )
    db.add(integration)
    await db.flush()

    tool_read = Tool(
        integration_id=integration.id,
        slug="list_items",
        name="List Items",
        description="List all items",
        method="GET",
        path="/items",
        parameters_schema={"type": "object", "properties": {"limit": {"type": "integer"}}},
        tool_type="read",
    )
    tool_write = Tool(
        integration_id=integration.id,
        slug="create_item",
        name="Create Item",
        description="Create a new item",
        method="POST",
        path="/items",
        parameters_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        tool_type="write",
    )
    db.add_all([tool_read, tool_write])
    await db.commit()
    await db.refresh(integration)
    return integration


# ── FastAPI TestClient via httpx ──────────────────────────────────────────

@pytest_asyncio.fixture()
async def client(engine, db: AsyncSession, test_api_key: tuple[APIKey, str]):
    """httpx.AsyncClient wired to the app with DB override."""
    # Clear the LRU cache so a fresh Settings is used
    get_settings.cache_clear()
    configure_secret_key("test-secret-key-for-pytest")

    app = create_app()

    # Override the get_db dependency to use our test session
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    _, raw_key = test_api_key

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
