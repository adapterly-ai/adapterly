"""MCP session manager."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from ..models.api_key import APIKey
from ..models.workspace import Workspace


@dataclass
class MCPSession:
    id: str
    account_id: str
    api_key_id: str
    workspace_id: str | None
    mode: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    is_admin: bool
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_active: bool = True
    # Notification queue for tools/list_changed etc.
    _notifications: list[dict] = field(default_factory=list)

    def touch(self):
        self.last_activity = time.time()

    def push_notification(self, notification: dict):
        self._notifications.append(notification)

    def drain_notifications(self) -> list[dict]:
        out = list(self._notifications)
        self._notifications.clear()
        return out


class SessionManager:
    SESSION_TIMEOUT = 1800  # 30 minutes

    def __init__(self):
        self._sessions: dict[str, MCPSession] = {}

    def get_or_create(
        self,
        session_id: str | None,
        api_key: APIKey,
        workspace: Workspace | None,
    ) -> MCPSession:
        self._cleanup_expired()

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.touch()
            return session

        new_id = str(uuid.uuid4())
        session = MCPSession(
            id=new_id,
            account_id=api_key.account_id,
            api_key_id=api_key.id,
            workspace_id=api_key.workspace_id,
            mode=api_key.mode,
            allowed_tools=api_key.allowed_tools or [],
            blocked_tools=api_key.blocked_tools or [],
            is_admin=api_key.is_admin,
        )
        self._sessions[new_id] = session
        return session

    def get(self, session_id: str) -> MCPSession | None:
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def close(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id].is_active = False
            del self._sessions[session_id]

    def notify_all(self, notification: dict):
        """Push notification to all active sessions."""
        for session in self._sessions.values():
            session.push_notification(notification)

    def _cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_activity > self.SESSION_TIMEOUT]
        for sid in expired:
            self._sessions[sid].is_active = False
            del self._sessions[sid]
