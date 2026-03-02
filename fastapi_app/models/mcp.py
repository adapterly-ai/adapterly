"""
MCP models - combines gateway_core models with monolith-only models.

Models shared with gateway (imported from gateway_core):
- ProjectIntegration, Project, MCPApiKey, MCPAuditLog, ErrorDiagnostic

Models unique to monolith (defined here):
- AgentProfile, MCPSession
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

# Re-export gateway_core models
from gateway_core.models import (  # noqa: F401
    Base,
    ErrorDiagnostic,
    MCPApiKey,
    MCPAuditLog,
    Project,
    ProjectIntegration,
)


class AgentProfile(Base):
    """Agent profile model - monolith only, mirrors mcp_agentprofile table."""

    __tablename__ = "mcp_agentprofile"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    include_tools = Column(JSON, default=list)
    mode = Column(String(20), default="safe")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships — uses backref to add .agent_profiles to Account and Project
    account = relationship("Account", back_populates="agent_profiles")
    project = relationship("Project", backref="agent_profiles")
    api_keys = relationship(
        "MCPApiKey",
        backref="profile",
        primaryjoin="AgentProfile.id == MCPApiKey.profile_id",
        foreign_keys=[MCPApiKey.profile_id],
    )

    def __repr__(self):
        return f"<AgentProfile(name='{self.name}')>"

    def is_tool_allowed(self, tool_name: str) -> bool:
        if not self.include_tools:
            return True
        return tool_name in self.include_tools


class MCPSession(Base):
    """MCP session model - monolith only, mirrors mcp_mcpsession table."""

    __tablename__ = "mcp_mcpsession"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    user_id = Column(Integer, nullable=True)
    mode = Column(String(20), default="safe")
    transport = Column(String(20), default="stdio")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tool_calls_count = Column(Integer, default=0)

    def __repr__(self):
        return f"<MCPSession(id='{self.session_id[:8]}...')>"
