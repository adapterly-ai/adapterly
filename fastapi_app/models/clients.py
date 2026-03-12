"""
Client models - mirrors Django clients_* tables.
"""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from gateway_core.models import Base


class Workspace(Base):
    """Workspace model - mirrors clients_workspace table."""

    __tablename__ = "clients_workspace"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    external_id = Column(String(255), nullable=True, index=True)
    settings = Column(JSON, default=dict)
    inherit_account_systems = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", backref="workspaces")
    members = relationship("WorkspaceMember", back_populates="workspace")

    __table_args__ = (UniqueConstraint("account_id", "external_id", name="unique_account_external_id"),)

    def __repr__(self):
        return f"<Workspace(id='{self.id}', name='{self.name}')>"


class WorkspaceMember(Base):
    """Workspace member model - mirrors clients_workspacemember table."""

    __tablename__ = "clients_workspacemember"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(String(36), ForeignKey("clients_workspace.id"), nullable=False)
    user_id = Column(Integer, nullable=False)  # FK to auth_user, not enforced
    role = Column(String(20), default="member")  # admin, member, viewer
    is_active = Column(Boolean, default=True)
    invited_by_id = Column(Integer, nullable=True)  # FK to auth_user, not enforced
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    workspace = relationship("Workspace", back_populates="members")

    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="unique_workspace_user"),)

    def __repr__(self):
        return f"<WorkspaceMember(workspace_id='{self.workspace_id}', user_id={self.user_id}, role='{self.role}')>"


class AdminSession(Base):
    """Admin session model - mirrors clients_adminsession table."""

    __tablename__ = "clients_adminsession"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_token = Column(String(64), unique=True, nullable=False, index=True)
    client_app_id = Column(Integer, nullable=True)  # FK to clients_clientapp, not enforced
    account_id = Column(Integer, ForeignKey("accounts_account.id"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("clients_workspace.id"), nullable=True)
    end_user_issuer = Column(String(255), default="")
    end_user_subject = Column(String(255), default="")
    role = Column(String(20), default="viewer")
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    account = relationship("Account", backref="admin_sessions")
    workspace = relationship("Workspace", backref="admin_sessions")

    def __repr__(self):
        return f"<AdminSession(id='{self.id}', role='{self.role}')>"

    @staticmethod
    def generate_token() -> str:
        """Generate a secure session token."""
        return secrets.token_urlsafe(48)

    def is_expired(self) -> bool:
        """Check if session is expired."""
        return datetime.utcnow() > self.expires_at

    def is_valid(self) -> bool:
        """Check if session is valid (not expired and not used)."""
        return not self.is_used and not self.is_expired()
