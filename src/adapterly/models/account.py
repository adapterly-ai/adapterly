"""Account and Member models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_id


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    members: Mapped[list["Member"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    workspaces = relationship("Workspace", back_populates="account", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="account", cascade="all, delete-orphan")


class Member(TimestampMixin, Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    display_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(20), default="admin")  # "owner" | "admin" | "member"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    account: Mapped["Account"] = relationship(back_populates="members")
