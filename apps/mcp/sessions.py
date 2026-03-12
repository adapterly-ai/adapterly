"""
MCP Session Manager for API and XHR (browser) sessions.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class SystemSession:
    """
    Represents an authenticated session to an external system.
    """

    system_alias: str
    interface_alias: str
    interface_type: str  # "api" or "xhr"

    # Authentication state
    is_authenticated: bool = False
    auth_headers: dict[str, str] = field(default_factory=dict)

    # For XHR sessions (browser-based)
    session_cookie: str | None = None
    csrf_token: str | None = None
    browser_context: Any | None = None  # Playwright browser context

    # Session metadata
    created_at: timezone.datetime | None = None
    expires_at: timezone.datetime | None = None
    last_used_at: timezone.datetime | None = None

    def is_expired(self) -> bool:
        """Check if session has expired."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    def touch(self):
        """Update last used timestamp."""
        self.last_used_at = timezone.now()


class MCPSessionManager:
    """
    Manages sessions to external systems for MCP tool calls.

    Handles both API sessions (token-based) and XHR sessions (browser-based).
    """

    def __init__(self, account_id: int):
        """
        Initialize session manager.

        Args:
            account_id: Account ID to manage sessions for
        """
        self.account_id = account_id
        self._sessions: dict[str, SystemSession] = {}
        self._browser = None  # Playwright browser instance

    def get_session_key(self, system_alias: str, interface_alias: str) -> str:
        """Generate session key for a system/interface pair."""
        return f"{system_alias}:{interface_alias}"

    async def get_session(self, system_alias: str, interface_alias: str = "default") -> SystemSession | None:
        """
        Get or create a session for a system.

        Args:
            system_alias: System alias (e.g., "salesforce")
            interface_alias: Interface alias (e.g., "rest", "graphql")

        Returns:
            SystemSession if authenticated, None if authentication failed
        """
        key = self.get_session_key(system_alias, interface_alias)

        # Return existing valid session
        if key in self._sessions:
            session = self._sessions[key]
            if session.is_authenticated and not session.is_expired():
                session.touch()
                return session

        # Create new session
        session = await self._create_session(system_alias, interface_alias)
        if session and session.is_authenticated:
            self._sessions[key] = session

        return session

    async def _create_session(self, system_alias: str, interface_alias: str) -> SystemSession | None:
        """
        Create a new session for a system.
        """
        from apps.systems.models import AccountSystem, Interface, System

        try:
            # Get system and interface
            system = System.objects.get(alias=system_alias, is_active=True)
            interface = Interface.objects.get(system=system, alias=interface_alias)

            # Get account-specific credentials
            account_system = AccountSystem.objects.filter(
                account_id=self.account_id, system=system, is_enabled=True
            ).first()

            if not account_system:
                logger.warning(f"No enabled AccountSystem for {system_alias} in account {self.account_id}")
                return None

            # Create session based on interface type
            if interface.type == "XHR":
                return await self._create_xhr_session(system, interface, account_system)
            else:
                return await self._create_api_session(system, interface, account_system)

        except System.DoesNotExist:
            logger.error(f"System not found: {system_alias}")
            return None
        except Interface.DoesNotExist:
            logger.error(f"Interface not found: {system_alias}/{interface_alias}")
            return None
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return None

    async def _create_api_session(self, system, interface, account_system) -> SystemSession:
        """Create an API (REST/GraphQL) session."""
        session = SystemSession(
            system_alias=system.alias, interface_alias=interface.alias, interface_type="api", created_at=timezone.now()
        )

        # Get auth headers from account system
        auth_headers = account_system.get_auth_headers()
        if auth_headers:
            session.auth_headers = auth_headers
            session.is_authenticated = True

        # Check for OAuth token refresh
        if account_system.is_oauth_expired():
            refreshed = await self._refresh_oauth_token(account_system)
            if refreshed:
                session.auth_headers = account_system.get_auth_headers()
                session.is_authenticated = True
            else:
                session.is_authenticated = False

        return session

    async def _create_xhr_session(self, system, interface, account_system) -> SystemSession:
        """Create an XHR (browser-based) session."""
        session = SystemSession(
            system_alias=system.alias, interface_alias=interface.alias, interface_type="xhr", created_at=timezone.now()
        )

        # Check for existing session cookie
        if account_system.session_cookie and not account_system.is_session_expired():
            session.session_cookie = account_system.session_cookie
            session.csrf_token = account_system.csrf_token
            session.is_authenticated = True
            return session

        # Need to perform browser login
        try:
            from apps.mcp.browser.session import BrowserSessionManager

            browser_manager = BrowserSessionManager()
            result = await browser_manager.login(system=system, interface=interface, account_system=account_system)

            if result.success:
                session.session_cookie = result.session_cookie
                session.csrf_token = result.csrf_token
                session.is_authenticated = True

                # Save session to database
                account_system.session_cookie = result.session_cookie
                account_system.csrf_token = result.csrf_token
                account_system.session_expires_at = result.expires_at
                account_system.save(update_fields=["session_cookie", "csrf_token", "session_expires_at"])
            else:
                logger.error(f"Browser login failed: {result.error}")
                session.is_authenticated = False

        except ImportError:
            logger.warning("Playwright not available for browser sessions")
            session.is_authenticated = False
        except Exception as e:
            logger.error(f"Browser login error: {e}")
            session.is_authenticated = False

        return session

    async def _refresh_oauth_token(self, account_system) -> bool:
        """Refresh OAuth token if expired."""
        # TODO: Implement OAuth token refresh
        logger.warning("OAuth token refresh not implemented")
        return False

    async def invalidate_session(self, system_alias: str, interface_alias: str = "default"):
        """Invalidate and remove a session."""
        key = self.get_session_key(system_alias, interface_alias)

        if key in self._sessions:
            session = self._sessions[key]

            # Close browser context if XHR session
            if session.browser_context:
                try:
                    await session.browser_context.close()
                except Exception as e:
                    logger.warning(f"Error closing browser context: {e}")

            del self._sessions[key]

    async def close_all(self):
        """Close all sessions."""
        for key in list(self._sessions.keys()):
            await self.invalidate_session(*key.split(":"))

        # Close browser if open
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

    def get_auth_headers(self, system_alias: str, interface_alias: str = "default") -> dict[str, str]:
        """Get auth headers for a system (synchronous version)."""
        key = self.get_session_key(system_alias, interface_alias)

        if key in self._sessions:
            session = self._sessions[key]
            if session.is_authenticated:
                return session.auth_headers

        return {}


def create_session_id() -> str:
    """Generate a unique session ID."""
    return f"mcp_{uuid.uuid4().hex[:16]}"
