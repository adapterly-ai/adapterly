"""
SQLAlchemy models for the FastAPI app.

Core models (System, Action, etc.) are defined in gateway_core.models
and re-exported here. Monolith-only models (Account, AgentProfile, etc.)
are defined locally.
"""

# Trigger mapper configuration so backrefs (Account→MCPApiKey, AgentProfile→MCPApiKey)
# are applied. Without this, lazy mapper config means MCPApiKey.account/.profile
# aren't available when dependencies.py accesses them via selectinload().
from sqlalchemy.orm import configure_mappers as _configure_mappers

from .accounts import Account
from .base import Base
from .clients import (
    AdminSession,
    Workspace,
    WorkspaceMember,
)
from .mcp import (
    AgentProfile,
    ErrorDiagnostic,
    MCPApiKey,
    MCPAuditLog,
    MCPSession,
    Project,
    ProjectIntegration,
)
from .systems import (
    AccountSystem,
    Action,
    Interface,
    Resource,
    System,
)

_configure_mappers()

__all__ = [
    "Base",
    "Account",
    "MCPApiKey",
    "AgentProfile",
    "MCPSession",
    "MCPAuditLog",
    "ErrorDiagnostic",
    "Project",
    "ProjectIntegration",
    "System",
    "Interface",
    "Resource",
    "Action",
    "AccountSystem",
    "Workspace",
    "WorkspaceMember",
    "AdminSession",
]
