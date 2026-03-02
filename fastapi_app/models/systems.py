"""
System models - re-exports from gateway_core.models.

In monolith mode, these map to the same Django-managed PostgreSQL tables.
The gateway_core models are the canonical definitions.
"""

from gateway_core.models import (  # noqa: F401
    AccountSystem,
    Action,
    Interface,
    Resource,
    System,
)

# Re-export decrypt_value for any code that imports it from here
from gateway_core.crypto import decrypt_value  # noqa: F401
