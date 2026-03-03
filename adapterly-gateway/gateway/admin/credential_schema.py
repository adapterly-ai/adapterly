"""
Dynamic credential field schema from adapter auth_steps.

Reads Interface.auth to determine which credential fields a system needs.
Falls back to auth.type-based defaults when auth_steps are not available.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_core.models import Interface, System


@dataclass
class CredentialField:
    name: str
    label: str
    type: str  # "string"
    required: bool = True
    sensitive: bool = False

    @property
    def input_type(self) -> str:
        return "password" if self.sensitive else "text"


# Default field sets per auth type
_AUTH_TYPE_DEFAULTS: dict[str, list[CredentialField]] = {
    "bearer": [
        CredentialField(name="api_key", label="API Key", type="string", sensitive=True),
    ],
    "drf_token": [
        CredentialField(name="username", label="Username", type="string"),
        CredentialField(name="password", label="Password", type="string", sensitive=True),
    ],
    "oauth2_password": [
        CredentialField(name="username", label="Username", type="string"),
        CredentialField(name="password", label="Password", type="string", sensitive=True),
        CredentialField(name="client_id", label="Client ID", type="string", required=False),
        CredentialField(name="client_secret", label="Client Secret", type="string", required=False, sensitive=True),
    ],
    "basic": [
        CredentialField(name="username", label="Username", type="string"),
        CredentialField(name="password", label="Password", type="string", sensitive=True),
    ],
}


def _is_sensitive_field(name: str, field_def: dict) -> bool:
    """Determine if a field should be masked."""
    if field_def.get("sensitive"):
        return True
    return name in ("password", "api_key", "token", "secret", "client_secret")


def _fields_from_auth_steps(auth_config: dict) -> list[CredentialField] | None:
    """Extract credential fields from auth.auth_steps[].input_fields."""
    auth_steps = auth_config.get("auth_steps", [])
    if not auth_steps:
        return None

    fields: list[CredentialField] = []
    for step in sorted(auth_steps, key=lambda s: s.get("step_order", 0)):
        input_fields = step.get("input_fields", {})
        for name, field_def in input_fields.items():
            fields.append(
                CredentialField(
                    name=name,
                    label=field_def.get("label", name.replace("_", " ").title()),
                    type=field_def.get("type", "string"),
                    required=field_def.get("required", True),
                    sensitive=_is_sensitive_field(name, field_def),
                )
            )

    return fields if fields else None


def _fields_from_auth_type(auth_config: dict) -> list[CredentialField]:
    """Fallback: determine fields from auth.type."""
    auth_type = auth_config.get("type", "")
    return list(_AUTH_TYPE_DEFAULTS.get(auth_type, _AUTH_TYPE_DEFAULTS["bearer"]))


async def get_credential_fields(system: System, db: AsyncSession) -> list[CredentialField]:
    """
    Get credential fields for a system.

    Priority:
    1. Interface.auth.auth_steps[].input_fields (from adapter YAML)
    2. Fallback based on Interface.auth.type
    """
    # Get the system's first interface (most systems have one)
    stmt = select(Interface).where(Interface.system_id == system.id).limit(1)
    result = await db.execute(stmt)
    interface = result.scalar_one_or_none()

    if not interface or not interface.auth:
        return list(_AUTH_TYPE_DEFAULTS["bearer"])

    auth_config = interface.auth

    # Try auth_steps first
    fields = _fields_from_auth_steps(auth_config)
    if fields:
        return fields

    # Fallback to auth.type
    return _fields_from_auth_type(auth_config)
