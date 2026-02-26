"""
System models - mirrors Django systems_* tables.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..crypto import decrypt_value
from .base import Base


class System(Base):
    """System model - mirrors systems_system table."""

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
    is_confirmed = Column(Boolean, default=False)  # True when tested with working integration
    confirmed_at = Column(DateTime, nullable=True)  # When first confirmed working
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    interfaces = relationship("Interface", back_populates="system")
    account_systems = relationship("AccountSystem", back_populates="system")

    def __repr__(self):
        return f"<System(alias='{self.alias}', name='{self.display_name}')>"


class Interface(Base):
    """Interface model - mirrors systems_interface table."""

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
    graphql_schema = Column(JSON, default=dict)  # Cached GraphQL introspection schema

    # Relationships
    system = relationship("System", back_populates="interfaces")
    resources = relationship("Resource", back_populates="interface")

    def __repr__(self):
        return f"<Interface(system='{self.system.alias if self.system else '?'}', alias='{self.alias}')>"


class Resource(Base):
    """Resource model - mirrors systems_resource table."""

    __tablename__ = "systems_resource"

    id = Column(Integer, primary_key=True)
    interface_id = Column(Integer, ForeignKey("systems_interface.id"), nullable=False)
    alias = Column(String(120), default="")
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")

    # Relationships
    interface = relationship("Interface", back_populates="resources")
    actions = relationship("Action", back_populates="resource")

    def __repr__(self):
        return f"<Resource(alias='{self.alias}', name='{self.name}')>"


class Action(Base):
    """Action model - mirrors systems_action table."""

    __tablename__ = "systems_action"

    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("systems_resource.id"), nullable=False)
    alias = Column(String(120), default="")
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    method = Column(String(8), nullable=False)  # GET, POST, PUT, PATCH, DELETE
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

    # Relationships
    resource = relationship("Resource", back_populates="actions")

    def __repr__(self):
        return f"<Action(name='{self.name}', method='{self.method}')>"


class AccountSystem(Base):
    """Account-System connection - mirrors systems_accountsystem table."""

    __tablename__ = "systems_accountsystem"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    system_id = Column(Integer, ForeignKey("systems_system.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=True)

    # Credentials (encrypted in Django, stored as-is here for read-only)
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

    # Relationships
    account = relationship("Account", backref="account_systems")
    system = relationship("System", back_populates="account_systems")
    project = relationship("Project", back_populates="account_systems")

    def __repr__(self):
        return f"<AccountSystem(account_id={self.account_id}, system='{self.system.alias if self.system else '?'}')>"

    def _decrypt(self, value: str | None) -> str | None:
        """Decrypt a Fernet-encrypted field value."""
        return decrypt_value(value)

    def get_auth_headers(self) -> dict:
        """Get authentication headers for this system."""
        headers = {}

        # Try OAuth token first
        oauth_tok = self._decrypt(self.oauth_token)
        if oauth_tok:
            token_prefix = (self.custom_settings or {}).get("token_prefix", "Bearer")
            headers["Authorization"] = f"{token_prefix} {oauth_tok}"
            return headers

        # Then try regular token
        tok = self._decrypt(self.token)
        if tok:
            token_prefix = (self.custom_settings or {}).get("token_prefix", "Bearer")
            headers["Authorization"] = f"{token_prefix} {tok}"
            return headers

        # Then try API key
        key = self._decrypt(self.api_key)
        if key:
            api_key_name = (self.custom_settings or {}).get("api_key_header", "X-API-Key")
            headers[api_key_name] = key
            return headers

        # Finally try basic auth
        uname = self.username
        pwd = self._decrypt(self.password)
        if uname and pwd:
            import base64

            credentials = f"{uname}:{pwd}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    def is_oauth_expired(self) -> bool:
        """Check if OAuth token is expired."""
        if not self.oauth_expires_at:
            return False
        expires = self.oauth_expires_at
        now = datetime.now(timezone.utc)
        # Handle both naive and aware datetimes from DB
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires
