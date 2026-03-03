"""Tests for gateway_core.auth — API key validation against SQLite."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from gateway_core.auth import validate_api_key
from gateway_core.models import MCPApiKey, Project

from .conftest import (
    ADMIN_RAW_KEY,
    RAW_API_KEY,
    RAW_API_KEY_PREFIX,
    create_test_data,
)


class TestValidateApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_key_and_project(self, db):
        await create_test_data(db)
        api_key, project = await validate_api_key(RAW_API_KEY, db)
        assert isinstance(api_key, MCPApiKey)
        assert isinstance(project, Project)
        assert project.id == 1
        assert api_key.key_prefix == RAW_API_KEY_PREFIX

    @pytest.mark.asyncio
    async def test_admin_key_returns_none_project(self, db):
        await create_test_data(db)
        api_key, project = await validate_api_key(ADMIN_RAW_KEY, db)
        assert api_key.is_admin is True
        assert project is None

    @pytest.mark.asyncio
    async def test_empty_key_raises(self, db):
        with pytest.raises(ValueError, match="Empty API key"):
            await validate_api_key("", db)

    @pytest.mark.asyncio
    async def test_unknown_prefix_raises(self, db):
        await create_test_data(db)
        with pytest.raises(ValueError, match="Invalid API key"):
            await validate_api_key("ak_unknown_1234567890abcdef", db)

    @pytest.mark.asyncio
    async def test_wrong_hash_raises(self, db):
        await create_test_data(db)
        # Same prefix but different full key
        bad_key = RAW_API_KEY_PREFIX + "XXXXXXXXXXXXXXXXXXXXXX"
        with pytest.raises(ValueError, match="Invalid API key"):
            await validate_api_key(bad_key, db)

    @pytest.mark.asyncio
    async def test_expired_key_raises(self, db):
        data = await create_test_data(db)
        # Make the key expired
        api_key = data["api_key"]
        api_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

        with pytest.raises(ValueError, match="API key has expired"):
            await validate_api_key(RAW_API_KEY, db)

    @pytest.mark.asyncio
    async def test_inactive_key_raises(self, db):
        data = await create_test_data(db)
        api_key = data["api_key"]
        api_key.is_active = False
        await db.commit()

        with pytest.raises(ValueError, match="Invalid API key"):
            await validate_api_key(RAW_API_KEY, db)

    @pytest.mark.asyncio
    async def test_last_used_at_updated(self, db):
        data = await create_test_data(db)
        assert data["api_key"].last_used_at is None

        await validate_api_key(RAW_API_KEY, db)

        # Re-query to check last_used_at
        result = await db.execute(
            text("SELECT last_used_at FROM mcp_mcpapikey WHERE id = :id"),
            {"id": 1},
        )
        row = result.fetchone()
        assert row[0] is not None
