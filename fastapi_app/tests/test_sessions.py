"""Tests for SessionManager and MCPSession."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.mcp.sessions import MCPSession, SessionManager


class TestMCPSession:
    def test_touch_updates_last_activity(self):
        session = MCPSession(
            id="test-session",
            server=AsyncMock(),
            account_id=1,
            api_key_id=1,
            mode="safe",
        )
        original = session.last_activity
        # Small delay to ensure time difference
        time.sleep(0.01)
        session.touch()
        assert session.last_activity > original


@pytest.mark.asyncio
class TestSessionManager:
    async def test_create_new_session(self, db):
        """get_or_create with no session_id creates a new session."""
        manager = SessionManager()
        api_key = AsyncMock()
        api_key.account_id = 1
        api_key.id = 1
        api_key.is_admin = False
        api_key.mode = "safe"

        with patch("fastapi_app.mcp.sessions.MCPServer") as MockServer:
            mock_server = AsyncMock()
            MockServer.return_value = mock_server
            session = await manager.get_or_create(
                session_id=None,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )
        assert session is not None
        assert session.account_id == 1
        assert session.is_active is True

    async def test_reuse_existing_session(self, db):
        """Same session_id returns the same session."""
        manager = SessionManager()
        api_key = AsyncMock()
        api_key.account_id = 1
        api_key.id = 1
        api_key.is_admin = False
        api_key.mode = "safe"

        with patch("fastapi_app.mcp.sessions.MCPServer") as MockServer:
            mock_server = AsyncMock()
            MockServer.return_value = mock_server
            session1 = await manager.get_or_create(
                session_id=None,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )
            session2 = await manager.get_or_create(
                session_id=session1.id,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )
        assert session1.id == session2.id

    async def test_expired_session_cleaned_up(self, db):
        """Sessions past timeout are removed during cleanup."""
        manager = SessionManager()
        api_key = AsyncMock()
        api_key.account_id = 1
        api_key.id = 1
        api_key.is_admin = False
        api_key.mode = "safe"

        with patch("fastapi_app.mcp.sessions.MCPServer") as MockServer:
            mock_server = AsyncMock()
            MockServer.return_value = mock_server
            session = await manager.get_or_create(
                session_id=None,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )
            # Force expiration
            session.last_activity = time.time() - manager.SESSION_TIMEOUT - 1

            # Next get_or_create triggers cleanup
            session2 = await manager.get_or_create(
                session_id=None,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )

        assert session.id != session2.id
        assert session.id not in manager._sessions

    async def test_close_session(self, db):
        """Close removes session and marks inactive."""
        manager = SessionManager()
        api_key = AsyncMock()
        api_key.account_id = 1
        api_key.id = 1
        api_key.is_admin = False
        api_key.mode = "safe"

        with patch("fastapi_app.mcp.sessions.MCPServer") as MockServer:
            mock_server = AsyncMock()
            MockServer.return_value = mock_server
            session = await manager.get_or_create(
                session_id=None,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )
            sid = session.id
            await manager.close(sid)

        assert sid not in manager._sessions
        assert session.is_active is False

    async def test_close_nonexistent_noop(self):
        """Closing a non-existent session doesn't raise."""
        manager = SessionManager()
        await manager.close("nonexistent-id")

    async def test_get_active_sessions(self, db):
        """get_active_sessions returns list of session info dicts."""
        manager = SessionManager()
        api_key = AsyncMock()
        api_key.account_id = 1
        api_key.id = 1
        api_key.is_admin = False
        api_key.mode = "safe"

        with patch("fastapi_app.mcp.sessions.MCPServer") as MockServer:
            mock_server = AsyncMock()
            MockServer.return_value = mock_server
            await manager.get_or_create(
                session_id=None,
                api_key=api_key,
                api_key_string="ak_test",
                db=db,
            )

        sessions = manager.get_active_sessions()
        assert len(sessions) == 1
        assert sessions[0]["account_id"] == 1
