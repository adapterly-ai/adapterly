"""Account and Member models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_id


# Plan limits: workspaces, connections, members, tool_calls_per_month
PLAN_LIMITS: dict[str, dict] = {
    "free": {
        "workspaces": 1,
        "connections": 3,
        "members": 1,
        "tool_calls_monthly": 1_000,
    },
    "pro": {
        "workspaces": 5,
        "connections": -1,  # unlimited
        "members": 1,
        "tool_calls_monthly": 50_000,
    },
    "team": {
        "workspaces": -1,
        "connections": -1,
        "members": 5,
        "tool_calls_monthly": 200_000,
    },
    "enterprise": {
        "workspaces": -1,
        "connections": -1,
        "members": -1,
        "tool_calls_monthly": -1,
    },
    "self_hosted": {
        "workspaces": -1,
        "connections": -1,
        "members": -1,
        "tool_calls_monthly": -1,
    },
}


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(21), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Billing / plan
    plan: Mapped[str] = mapped_column(String(20), default="free")  # free|pro|team|enterprise|self_hosted
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    usage_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    # Relationships
    members: Mapped[list["Member"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    workspaces = relationship("Workspace", back_populates="account", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="account", cascade="all, delete-orphan")

    @property
    def limits(self) -> dict:
        return PLAN_LIMITS.get(self.plan, PLAN_LIMITS["free"])


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
