"""Connection model – links a workspace to an integration with credentials."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_id


class Connection(TimestampMixin, Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True)
    base_url_override: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Encrypted credentials (Fernet)
    credentials: Mapped[dict] = mapped_column(JSON, default=dict)

    # Custom settings (e.g. api_key_header, token_prefix)
    custom_settings: Mapped[dict] = mapped_column(JSON, default=dict)

    # External project/entity ID for auto-injection
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    workspace = relationship("Workspace", back_populates="connections")
    integration = relationship("Integration", back_populates="connections")
