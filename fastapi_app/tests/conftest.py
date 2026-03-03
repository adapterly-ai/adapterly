"""Shared fixtures for FastAPI MCP tests."""

import hashlib
import os

# Set env before any app imports
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("DEBUG", "true")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway_core.crypto import configure_secret_key
from gateway_core.models import (
    Action,
    Base,
    Interface,
    MCPApiKey,
    Project,
    ProjectIntegration,
    Resource,
    System,
)

TEST_SECRET = "test-secret-key-for-ci"

RAW_API_KEY = "ak_live_test1234567890abcdef"
RAW_API_KEY_HASH = hashlib.sha256(RAW_API_KEY.encode()).hexdigest()
RAW_API_KEY_PREFIX = RAW_API_KEY[:10]

ADMIN_RAW_KEY = "ak_admin_te1234567890abcdef"
ADMIN_KEY_HASH = hashlib.sha256(ADMIN_RAW_KEY.encode()).hexdigest()
ADMIN_KEY_PREFIX = ADMIN_RAW_KEY[:10]


@pytest.fixture(autouse=True)
def _setup_crypto():
    """Configure crypto secret key before every test."""
    configure_secret_key(TEST_SECRET)


@pytest_asyncio.fixture
async def engine():
    """Create an in-memory SQLite async engine."""
    eng = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    """Provide a fresh async session per test."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


async def create_test_data(db: AsyncSession) -> dict:
    """Insert a minimal set of related objects and return them keyed by name."""
    system = System(
        id=1,
        name="testsystem",
        alias="testsys",
        display_name="Test System",
        description="A test system",
        system_type="api",
        is_active=True,
    )
    db.add(system)

    interface = Interface(
        id=1,
        system_id=1,
        alias="testapi",
        name="Test API",
        type="API",
        base_url="https://api.example.com",
        auth={"type": "bearer"},
    )
    db.add(interface)

    resource = Resource(
        id=1,
        interface_id=1,
        alias="users",
        name="Users",
        description="User management",
    )
    db.add(resource)

    action_read = Action(
        id=1,
        resource_id=1,
        alias="list",
        name="List Users",
        description="List all users",
        method="GET",
        path="/api/v1/users",
        is_mcp_enabled=True,
    )
    action_write = Action(
        id=2,
        resource_id=1,
        alias="create",
        name="Create User",
        description="Create a new user",
        method="POST",
        path="/api/v1/users",
        is_mcp_enabled=True,
    )
    db.add_all([action_read, action_write])

    project = Project(
        id=1,
        account_id=1,
        name="Test Project",
        slug="test-project",
        description="A test project",
    )
    db.add(project)

    integration = ProjectIntegration(
        id=1,
        project_id=1,
        system_id=1,
        credential_source="account",
        external_id="ext-123",
        is_enabled=True,
    )
    db.add(integration)

    api_key = MCPApiKey(
        id=1,
        account_id=1,
        name="Test Key",
        key_prefix=RAW_API_KEY_PREFIX,
        key_hash=RAW_API_KEY_HASH,
        project_id=1,
        is_admin=False,
        mode="safe",
        is_active=True,
    )
    db.add(api_key)

    admin_key = MCPApiKey(
        id=2,
        account_id=1,
        name="Admin Key",
        key_prefix=ADMIN_KEY_PREFIX,
        key_hash=ADMIN_KEY_HASH,
        project_id=None,
        is_admin=True,
        mode="power",
        is_active=True,
    )
    db.add(admin_key)

    await db.commit()

    return {
        "system": system,
        "interface": interface,
        "resource": resource,
        "action_read": action_read,
        "action_write": action_write,
        "project": project,
        "integration": integration,
        "api_key": api_key,
        "admin_key": admin_key,
    }


@pytest_asyncio.fixture
async def test_data(db):
    """Insert test data into the database."""
    return await create_test_data(db)


@pytest_asyncio.fixture
async def app(engine):
    """Create FastAPI test app with overridden DB dependency."""
    from fastapi_app.database import get_db
    from fastapi_app.main import app as real_app

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    real_app.dependency_overrides[get_db] = override_get_db
    yield real_app
    real_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    """Provide httpx async client bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
