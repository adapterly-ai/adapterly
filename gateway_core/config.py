"""
Gateway Core configuration.

DEPLOYMENT_MODE determines how the system behaves:
- monolith: Everything runs together (current behavior). Default.
- control_plane: Django-only, no tool execution. Serves Gateway Sync API.
- gateway: Standalone gateway with local SQLite. Syncs specs from control plane.
"""

import os
from enum import Enum


class DeploymentMode(str, Enum):
    MONOLITH = "monolith"
    CONTROL_PLANE = "control_plane"
    GATEWAY = "gateway"


def get_deployment_mode() -> DeploymentMode:
    """Get the current deployment mode from DEPLOYMENT_MODE env var."""
    mode = os.environ.get("DEPLOYMENT_MODE", "monolith").lower()
    try:
        return DeploymentMode(mode)
    except ValueError:
        return DeploymentMode.MONOLITH


def is_monolith() -> bool:
    return get_deployment_mode() == DeploymentMode.MONOLITH


def is_control_plane() -> bool:
    return get_deployment_mode() == DeploymentMode.CONTROL_PLANE


def is_gateway() -> bool:
    return get_deployment_mode() == DeploymentMode.GATEWAY
