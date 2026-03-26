"""API Key model for MCP authentication."""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_id

# Prefix for generated keys
KEY_PREFIX = "ak_"


def generate_api_key() -> tuple[str, str, str]:
    """Generate API key, returning (full_key, prefix, hash)."""
    raw = secrets.token_urlsafe(32)
    full_key = f"{KEY_PREFIX}{raw}"
    prefix = full_key[:12]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


class APIKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(255), default="Default")
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)

    # Permission model
    mode: Mapped[str] = mapped_column(String(10), default="safe")  # "safe" | "power"
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    blocked_tools: Mapped[list] = mapped_column(JSON, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    account = relationship("Account", back_populates="api_keys")
    workspace = relationship("Workspace", back_populates="api_keys")

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()
