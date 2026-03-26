"""Integration and Tool models."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_id


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    slug: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(50), default="other")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    auth_config: Mapped[dict] = mapped_column(JSON, default=dict)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    rate_limits: Mapped[dict] = mapped_column(JSON, default=dict)

    # Scope
    scope: Mapped[str] = mapped_column(String(10), index=True, default="public")  # "public" | "private"
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)

    source_spec_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    tools: Mapped[list["Tool"]] = relationship(back_populates="integration", cascade="all, delete-orphan")
    connections = relationship("Connection", back_populates="integration")


class Tool(TimestampMixin, Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(8), default="GET")
    path: Mapped[str] = mapped_column(String(500), default="")
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    parameters_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    pagination: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_type: Mapped[str] = mapped_column(String(20), default="read")  # "read" | "write"
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    integration: Mapped["Integration"] = relationship(back_populates="tools")

    @property
    def mcp_name(self) -> str:
        """Full MCP tool name: {integration_slug}_{tool_slug}."""
        return f"{self.integration.slug}_{self.slug}"
