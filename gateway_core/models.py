"""
SQLAlchemy models for the gateway core.

These models define the gateway's local database schema.
In monolith mode, they mirror Django's tables (same table names).
In standalone gateway mode, they ARE the tables (SQLite).
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship

from .crypto import decrypt_value


class Base(DeclarativeBase):
    """Base class for all gateway SQLAlchemy models."""

    pass


# ---------------------------------------------------------------------------
# System / Adapter spec models (synced from control plane in gateway mode)
# ---------------------------------------------------------------------------


class System(Base):
    """System model — adapter definition."""

    __tablename__ = "systems_system"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    alias = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    variables = Column(JSON, default=dict)
    meta = Column(JSON, default=dict)
    schema_digest = Column(String(64), default="")
    system_type = Column(String(50), nullable=False)
    icon = Column(String(50), default="")
    website_url = Column(String(500), default="")
    docs_url = Column(String(500), default="")
    is_active = Column(Boolean, default=True)
    is_confirmed = Column(Boolean, default=False)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    interfaces = relationship("Interface", back_populates="system")
    account_systems = relationship("AccountSystem", back_populates="system")

    def __repr__(self):
        return f"<System(alias='{self.alias}')>"


class Interface(Base):
    """Interface model — API/GraphQL/XHR endpoint group."""

    __tablename__ = "systems_interface"

    id = Column(Integer, primary_key=True)
    system_id = Column(Integer, ForeignKey("systems_system.id"), nullable=False)
    alias = Column(String(120), default="")
    name = Column(String(120), nullable=False)
    type = Column(String(8), nullable=False)  # API, GRAPHQL, XHR
    base_url = Column(String(300), default="")
    auth = Column(JSON, default=dict)
    requires_browser = Column(Boolean, default=False)
    browser = Column(JSON, default=dict)
    rate_limits = Column(JSON, default=dict)
    graphql_schema = Column(JSON, default=dict)

    system = relationship("System", back_populates="interfaces")
    resources = relationship("Resource", back_populates="interface")

    def __repr__(self):
        return f"<Interface(alias='{self.alias}')>"


class Resource(Base):
    """Resource model — logical API resource group."""

    __tablename__ = "systems_resource"

    id = Column(Integer, primary_key=True)
    interface_id = Column(Integer, ForeignKey("systems_interface.id"), nullable=False)
    alias = Column(String(120), default="")
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")

    interface = relationship("Interface", back_populates="resources")
    actions = relationship("Action", back_populates="resource")

    def __repr__(self):
        return f"<Resource(alias='{self.alias}')>"


class Action(Base):
    """Action model — individual API endpoint / tool."""

    __tablename__ = "systems_action"

    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("systems_resource.id"), nullable=False)
    alias = Column(String(120), default="")
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    method = Column(String(8), nullable=False)
    path = Column(String(400), nullable=False)
    headers = Column(JSON, default=dict)
    parameters_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)
    pagination = Column(JSON, default=dict)
    errors = Column(JSON, default=dict)
    examples = Column(JSON, default=list)
    is_mcp_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resource = relationship("Resource", back_populates="actions")

    def __repr__(self):
        return f"<Action(name='{self.name}', method='{self.method}')>"


# ---------------------------------------------------------------------------
# Credential models (local-only in gateway mode)
# ---------------------------------------------------------------------------


class AccountSystem(Base):
    """Account-System credentials — local to the gateway."""

    __tablename__ = "systems_accountsystem"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    system_id = Column(Integer, ForeignKey("systems_system.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=True)

    # Credentials (Fernet-encrypted)
    username = Column(String(200), nullable=True)
    password = Column(String(500), nullable=True)
    api_key = Column(String(500), nullable=True)
    token = Column(String(1000), nullable=True)
    client_id = Column(String(200), nullable=True)
    client_secret = Column(String(500), nullable=True)

    # OAuth
    oauth_token = Column(Text, nullable=True)
    oauth_refresh_token = Column(Text, nullable=True)
    oauth_expires_at = Column(DateTime, nullable=True)

    # Session/XHR auth
    session_cookie = Column(Text, nullable=True)
    csrf_token = Column(String(500), nullable=True)
    session_expires_at = Column(DateTime, nullable=True)

    # Settings
    custom_settings = Column(JSON, default=dict)
    is_enabled = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    last_verified_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    system = relationship("System", back_populates="account_systems")
    project = relationship("Project", backref="account_systems")

    def __repr__(self):
        return f"<AccountSystem(account_id={self.account_id}, system_id={self.system_id})>"

    def _decrypt(self, value: str | None) -> str | None:
        return decrypt_value(value)

    def get_auth_headers(self) -> dict:
        """Get authentication headers for this system."""
        headers = {}

        oauth_tok = self._decrypt(self.oauth_token)
        if oauth_tok:
            token_prefix = (self.custom_settings or {}).get("token_prefix", "Bearer")
            headers["Authorization"] = f"{token_prefix} {oauth_tok}"
            return headers

        tok = self._decrypt(self.token)
        if tok:
            token_prefix = (self.custom_settings or {}).get("token_prefix", "Bearer")
            headers["Authorization"] = f"{token_prefix} {tok}"
            return headers

        key = self._decrypt(self.api_key)
        if key:
            api_key_name = (self.custom_settings or {}).get("api_key_header", "X-API-Key")
            headers[api_key_name] = key
            return headers

        uname = self.username
        pwd = self._decrypt(self.password)
        if uname and pwd:
            import base64

            credentials = f"{uname}:{pwd}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    def is_oauth_expired(self) -> bool:
        if not self.oauth_expires_at:
            return False
        expires = self.oauth_expires_at
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires


# ---------------------------------------------------------------------------
# MCP configuration models (synced from control plane in gateway mode)
# ---------------------------------------------------------------------------


class ProjectIntegration(Base):
    """Links a Project to a System with credential source and external ID."""

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

    project = relationship("Project", back_populates="integrations")
    system = relationship("System")

    def __repr__(self):
        return f"<ProjectIntegration(project_id={self.project_id}, system_id={self.system_id})>"


class Project(Base):
    """Project context for MCP operations."""

    __tablename__ = "mcp_project"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="")
    external_mappings = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    integrations = relationship("ProjectIntegration", back_populates="project", cascade="all, delete-orphan")
    api_keys = relationship("MCPApiKey", back_populates="project")

    __table_args__ = (UniqueConstraint("account_id", "slug", name="uix_project_account_slug"),)

    def __repr__(self):
        return f"<Project(slug='{self.slug}')>"

    def get_external_id(self, system_alias: str) -> str | None:
        if self.external_mappings:
            return self.external_mappings.get(system_alias)
        return None


class MCPApiKey(Base):
    """MCP API key for gateway authentication."""

    __tablename__ = "mcp_mcpapikey"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    created_by_id = Column(Integer, nullable=True)
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(10), nullable=False, index=True)
    key_hash = Column(String(128), nullable=False)
    profile_id = Column(Integer, nullable=True)
    project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=True)
    is_admin = Column(Boolean, default=False)
    mode = Column(String(20), default="safe")
    allowed_tools = Column(JSON, default=list)
    blocked_tools = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="api_keys")

    def __repr__(self):
        return f"<MCPApiKey(name='{self.name}', prefix='{self.key_prefix}')>"

    def check_key(self, key: str) -> bool:
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key_hash == self.key_hash

    async def mark_used(self, session):
        self.last_used_at = datetime.utcnow()
        session.add(self)
        await session.commit()


# ---------------------------------------------------------------------------
# Audit / diagnostic models (buffered locally, pushed to control plane)
# ---------------------------------------------------------------------------


class MCPAuditLog(Base):
    """Audit log entry — buffered locally, pushed to control plane."""

    __tablename__ = "mcp_mcpauditlog"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=True)
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
    # Gateway sync: False = not yet pushed to control plane
    synced = Column(Boolean, default=False)

    def __repr__(self):
        return f"<MCPAuditLog(tool='{self.tool_name}', success={self.success})>"


class ErrorDiagnostic(Base):
    """Error diagnostic — buffered locally, pushed to control plane."""

    __tablename__ = "mcp_errordiagnostic"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    system_alias = Column(String(100), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False, index=True)
    action_name = Column(String(255), default="")
    status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=False)
    error_data = Column(JSON, default=dict)
    category = Column(String(30), nullable=False, index=True)
    severity = Column(String(10), default="medium")
    diagnosis_summary = Column(String(500), nullable=False)
    diagnosis_detail = Column(Text, default="")
    has_fix = Column(Boolean, default=False)
    fix_description = Column(Text, default="")
    fix_action = Column(JSON, default=dict)
    status = Column(String(20), default="pending", index=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, default="")
    occurrence_count = Column(Integer, default=1)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    synced = Column(Boolean, default=False)

    def __repr__(self):
        return f"<ErrorDiagnostic(category='{self.category}', system='{self.system_alias}')>"
