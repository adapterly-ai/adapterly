"""
Account model - mirrors Django accounts_account table.

Defines relationships to gateway_core models (Project, MCPApiKey) via backref,
so gateway_core models don't need to know about Account.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from gateway_core.models import Base, MCPApiKey, Project


class Account(Base):
    """Account model - mirrors accounts_account table."""

    __tablename__ = "accounts_account"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    external_id = Column(String(255), unique=True, nullable=True, index=True)
    default_project_id = Column(Integer, ForeignKey("mcp_project.id"), nullable=True)

    # Relationships to gateway_core models
    # Explicit primaryjoin + foreign_keys needed because gateway_core models omit
    # FK constraints to accounts_account (Account table doesn't exist in standalone gateway).
    mcp_api_keys = relationship(
        "MCPApiKey",
        backref="account",
        primaryjoin="Account.id == MCPApiKey.account_id",
        foreign_keys=[MCPApiKey.account_id],
    )
    projects = relationship(
        "Project",
        backref="account",
        primaryjoin="Account.id == Project.account_id",
        foreign_keys=[Project.account_id],
    )
    default_project = relationship("Project", foreign_keys=[default_project_id])

    # Relationships to monolith-only models
    agent_profiles = relationship("AgentProfile", back_populates="account")

    def __repr__(self):
        return f"<Account(id={self.id}, name='{self.name}')>"
