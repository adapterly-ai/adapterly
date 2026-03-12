"""
MCP session management.
"""

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.mcp import MCPApiKey, Project
from .server import MCPServer


@dataclass
class MCPSession:
    """Represents an active MCP session."""

    id: str
    server: MCPServer
    account_id: int
    api_key_id: int
    mode: str
    project_id: int | None = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_active: bool = True

    def touch(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()


class SessionManager:
    """
    Manages MCP sessions.

    Sessions are stored in memory for now.
    TODO: Consider Redis for distributed deployments.
    """

    # Session timeout in seconds (30 minutes)
    SESSION_TIMEOUT = 1800

    def __init__(self):
        self._sessions: dict[str, MCPSession] = {}

    async def get_or_create(
        self,
        session_id: str | None,
        api_key: MCPApiKey,
        api_key_string: str,
        db: AsyncSession,
        project: Project | None = None,
    ) -> MCPSession:
        """Get existing session or create new one."""
        # Cleanup expired sessions
        self._cleanup_expired()

        # Try to get existing session
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.touch()
            return session

        # Create new session
        new_session_id = str(uuid.uuid4())

        # Mode directly from API key
        mode = api_key.mode

        # Create MCP server with project context
        server = MCPServer(
            account_id=api_key.account_id,
            api_key=api_key_string,
            api_key_id=api_key.id,
            is_admin=api_key.is_admin,
            mode=mode,
            transport="http",
            project=project,
            db=db,
        )

        # Initialize server
        await server.initialize()

        session = MCPSession(
            id=new_session_id,
            server=server,
            account_id=api_key.account_id,
            api_key_id=api_key.id,
            mode=mode,
            project_id=project.id if project else None,
        )

        self._sessions[new_session_id] = session
        return session

    async def get(self, session_id: str) -> MCPSession | None:
        """Get session by ID."""
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    async def close(self, session_id: str):
        """Close and remove a session."""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.is_active = False
            await session.server.close()
            del self._sessions[session_id]

    def _cleanup_expired(self):
        """Remove expired sessions."""
        now = time.time()
        expired = [sid for sid, session in self._sessions.items() if now - session.last_activity > self.SESSION_TIMEOUT]
        for sid in expired:
            session = self._sessions[sid]
            session.is_active = False
            del self._sessions[sid]

    def get_active_sessions(self) -> list:
        """Get list of active sessions (for admin/debugging)."""
        return [
            {
                "session_id": session.id,
                "account_id": session.account_id,
                "api_key_id": session.api_key_id,
                "mode": session.mode,
                "project_id": session.project_id,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
            }
            for session in self._sessions.values()
        ]
