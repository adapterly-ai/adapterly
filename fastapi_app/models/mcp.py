"""
MCP models - mirrors Django mcp_* tables.
"""

import hashlib
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base


class ProjectIntegration(Base):
    """
    Links a Project to a System with credential source and external ID.

    Mirrors Django mcp_projectintegration table.
    """

    __tablename__ = "mcp_projectintegration"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=False)
    system_id = Column(Integer, ForeignKey("systems_system.id"), nullable=False)
    credential_source = Column(String(20), default="account", nullable=False)
    external_id = Column(String(500), default="")
    is_enabled = Column(Boolean, default=True)
    custom_config = Column(JSON, default=dict)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="integrations")
    system = relationship("System")

    def __repr__(self):
        return f"<ProjectIntegration(project_id={self.project_id}, system_id={self.system_id})>"


class Project(Base):
    """
    Project model - represents a project context for MCP operations.

    Projects provide:
    - Token -> Project (1:1) binding for access control
    - External system mappings (e.g., jira: "PROJ-123", github: "org/repo")
    """

    __tablename__ = "mcp_project"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="")

    # External system mappings: {"jira": "PROJ-123", "github": "org/repo"}
    external_mappings = Column(JSON, default=dict)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", back_populates="projects", foreign_keys=[account_id])
    api_keys = relationship("MCPApiKey", back_populates="project")
    agent_profiles = relationship("AgentProfile", back_populates="project", cascade="all, delete-orphan")
    integrations = relationship("ProjectIntegration", back_populates="project", cascade="all, delete-orphan")
    account_systems = relationship("AccountSystem", back_populates="project")

    __table_args__ = (UniqueConstraint("account_id", "slug", name="uix_project_account_slug"),)

    def __repr__(self):
        return f"<Project(slug='{self.slug}', name='{self.name}')>"

    def get_external_id(self, system_alias: str) -> str | None:
        """Get external ID for a specific system."""
        if self.external_mappings:
            return self.external_mappings.get(system_alias)
        return None


class AgentProfile(Base):
    """Agent profile model - mirrors mcp_agentprofile table."""

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

    # Relationships
    account = relationship("Account", back_populates="agent_profiles")
    project = relationship("Project", back_populates="agent_profiles")
    api_keys = relationship("MCPApiKey", back_populates="profile")

    def __repr__(self):
        return f"<AgentProfile(name='{self.name}')>"

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed by this profile."""
        if not self.include_tools:
            return True
        return tool_name in self.include_tools


class MCPApiKey(Base):
    """MCP API key model - mirrors mcp_mcpapikey table."""

    __tablename__ = "mcp_mcpapikey"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    created_by_id = Column(Integer, nullable=True)  # FK to auth_user, not enforced
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(10), nullable=False, index=True)
    key_hash = Column(String(128), nullable=False)
    profile_id = Column(Integer, ForeignKey("mcp_agentprofile.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=True)
    is_admin = Column(Boolean, default=False)
    mode = Column(String(20), default="safe")
    allowed_tools = Column(JSON, default=list)
    blocked_tools = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    # Relationships
    account = relationship("Account", back_populates="mcp_api_keys")
    profile = relationship("AgentProfile", back_populates="api_keys")
    project = relationship("Project", back_populates="api_keys")

    def __repr__(self):
        return f"<MCPApiKey(name='{self.name}', prefix='{self.key_prefix}')>"

    def check_key(self, key: str) -> bool:
        """Check if the provided key matches."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key_hash == self.key_hash

    async def mark_used(self, session):
        """Update last used timestamp."""
        self.last_used_at = datetime.utcnow()
        session.add(self)
        await session.commit()


class MCPSession(Base):
    """MCP session model - mirrors mcp_mcpsession table."""

    __tablename__ = "mcp_mcpsession"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    user_id = Column(Integer, nullable=True)  # FK to auth_user, not enforced
    mode = Column(String(20), default="safe")
    transport = Column(String(20), default="stdio")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tool_calls_count = Column(Integer, default=0)

    def __repr__(self):
        return f"<MCPSession(id='{self.session_id[:8]}...')>"


class ErrorDiagnostic(Base):
    """Error diagnostic model - mirrors mcp_errordiagnostic table."""

    __tablename__ = "mcp_errordiagnostic"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    system_alias = Column(String(100), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False, index=True)
    action_name = Column(String(255), default="")

    # Error details
    status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=False)
    error_data = Column(JSON, default=dict)

    # Diagnosis
    category = Column(String(30), nullable=False, index=True)
    severity = Column(String(10), default="medium")
    diagnosis_summary = Column(String(500), nullable=False)
    diagnosis_detail = Column(Text, default="")

    # Fix suggestion
    has_fix = Column(Boolean, default=False)
    fix_description = Column(Text, default="")
    fix_action = Column(JSON, default=dict)

    # Review workflow
    status = Column(String(20), default="pending", index=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, default="")

    # Occurrence tracking
    occurrence_count = Column(Integer, default=1)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<ErrorDiagnostic(category='{self.category}', system='{self.system_alias}', status='{self.status}')>"


class MCPAuditLog(Base):
    """MCP audit log model - mirrors mcp_mcpauditlog table."""

    __tablename__ = "mcp_mcpauditlog"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    user_id = Column(Integer, nullable=True)  # FK to auth_user, not enforced
    tool_name = Column(String(255), nullable=False, index=True)
    tool_type = Column(String(50), nullable=False)
    parameters = Column(JSON, default=dict)
    result_summary = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    success = Column(Boolean, default=True)
    error_message = Column(Text, default="")
    reasoning = Column(Text, default="")
    intent = Column(String(500), default="")
    context_summary = Column(Text, default="")
    is_reversible = Column(Boolean, default=False)
    rollback_data = Column(JSON, default=dict)
    rolled_back = Column(Boolean, default=False)
    rolled_back_at = Column(DateTime, nullable=True)
    rollback_audit_id = Column(Integer, nullable=True)
    session_id = Column(String(100), default="", index=True)
    transport = Column(String(20), default="stdio")
    mode = Column(String(20), default="safe")
    correlation_id = Column(String(100), default="", index=True)
    parent_audit_id = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<MCPAuditLog(tool='{self.tool_name}', success={self.success})>"
