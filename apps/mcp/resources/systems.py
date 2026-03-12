"""
MCP Resources for systems.

Provides read-only access to system configurations and schemas.
"""

import logging
from typing import Any

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


class SystemResources:
    """
    Resource provider for systems.

    URI patterns:
    - systems:// - List all systems
    - systems://{alias} - System details
    - systems://{alias}/schema - System actions and schemas
    """

    def __init__(self, account_id: int):
        self.account_id = account_id

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available system resources."""
        from apps.systems.models import AccountSystem

        resources = []

        # Base resource
        resources.append(
            {
                "uri": "systems://",
                "name": "All Systems",
                "description": "List of all available systems",
                "mimeType": "application/json",
            }
        )

        # Per-system resources
        def _get_account_systems():
            return list(
                AccountSystem.objects.filter(account_id=self.account_id, is_enabled=True).select_related("system")
            )

        account_systems = await sync_to_async(_get_account_systems, thread_sensitive=False)()

        for acc_sys in account_systems:
            system = acc_sys.system
            resources.append(
                {
                    "uri": f"systems://{system.alias}",
                    "name": system.display_name or system.name,
                    "description": system.description or f"Details for {system.name}",
                    "mimeType": "application/json",
                }
            )
            resources.append(
                {
                    "uri": f"systems://{system.alias}/schema",
                    "name": f"{system.display_name or system.name} Schema",
                    "description": f"Actions and schemas for {system.name}",
                    "mimeType": "application/json",
                }
            )

        return resources

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a system resource."""
        # Parse URI
        if uri == "systems://":
            return await self._list_systems()

        if uri.startswith("systems://"):
            path = uri[len("systems://") :]
            parts = path.split("/")

            if len(parts) == 1:
                return await self._get_system(parts[0])
            elif len(parts) == 2 and parts[1] == "schema":
                return await self._get_system_schema(parts[0])

        return {"error": f"Unknown resource: {uri}"}

    async def _list_systems(self) -> dict[str, Any]:
        """List all available systems."""
        from apps.systems.models import AccountSystem

        def _get_account_systems():
            return list(
                AccountSystem.objects.filter(account_id=self.account_id, is_enabled=True).select_related("system")
            )

        account_systems = await sync_to_async(_get_account_systems, thread_sensitive=False)()

        systems = []
        for acc_sys in account_systems:
            system = acc_sys.system
            systems.append(
                {
                    "alias": system.alias,
                    "name": system.display_name or system.name,
                    "description": system.description,
                    "type": system.system_type,
                    "is_verified": acc_sys.is_verified,
                    "last_verified_at": acc_sys.last_verified_at.isoformat() if acc_sys.last_verified_at else None,
                }
            )

        return {"systems": systems, "count": len(systems)}

    async def _get_system(self, alias: str) -> dict[str, Any]:
        """Get system details."""
        from apps.systems.models import AccountSystem, Interface, System

        def _get_data():
            try:
                system = System.objects.get(alias=alias, is_active=True)
            except System.DoesNotExist:
                return {"error": f"System not found: {alias}"}

            try:
                acc_sys = AccountSystem.objects.get(account_id=self.account_id, system=system, is_enabled=True)
            except AccountSystem.DoesNotExist:
                return {"error": f"System not enabled for account: {alias}"}

            interfaces = list(Interface.objects.filter(system=system).values("alias", "name", "type", "base_url"))

            return {
                "alias": system.alias,
                "name": system.display_name or system.name,
                "description": system.description,
                "type": system.system_type,
                "website_url": system.website_url,
                "interfaces": interfaces,
                "is_verified": acc_sys.is_verified,
                "last_error": acc_sys.last_error if not acc_sys.is_verified else None,
            }

        return await sync_to_async(_get_data, thread_sensitive=False)()

    async def _get_system_schema(self, alias: str) -> dict[str, Any]:
        """Get system actions and schemas."""
        from apps.systems.models import AccountSystem, Action, System

        def _get_schema():
            try:
                system = System.objects.get(alias=alias, is_active=True)
            except System.DoesNotExist:
                return {"error": f"System not found: {alias}"}

            if not AccountSystem.objects.filter(account_id=self.account_id, system=system, is_enabled=True).exists():
                return {"error": f"System not enabled for account: {alias}"}

            actions = list(
                Action.objects.filter(resource__interface__system=system).select_related(
                    "resource", "resource__interface"
                )
            )

            action_list = []
            for action in actions:
                action_list.append(
                    {
                        "name": f"{system.alias}_{action.resource.alias}_{action.alias}",
                        "interface": action.resource.interface.alias,
                        "resource": action.resource.alias,
                        "action": action.alias,
                        "method": action.method,
                        "path": action.path,
                        "description": action.description,
                        "parameters_schema": action.parameters_schema,
                        "output_schema": action.output_schema,
                    }
                )

            return {"system": alias, "actions": action_list, "count": len(action_list)}

        return await sync_to_async(_get_schema, thread_sensitive=False)()


def get_system_resources(account_id: int) -> SystemResources:
    """Get system resources provider for an account."""
    return SystemResources(account_id)
