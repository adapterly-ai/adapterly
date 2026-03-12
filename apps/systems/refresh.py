"""
Adapter refresh logic — re-fetch an OpenAPI spec and sync changes to the database.

Usage:
    from apps.systems.refresh import refresh_adapter
    result = refresh_adapter(system, dry_run=True)
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field

import requests
import yaml
from django.db import transaction
from django.utils import timezone

from apps.systems.adapter_generator import AdapterGenerator, GeneratedSystem
from apps.systems.models import Action, System

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    system_alias: str
    spec_changed: bool
    old_digest: str
    new_digest: str
    new_actions: list[str] = field(default_factory=list)
    updated_actions: list[str] = field(default_factory=list)
    unchanged_actions: list[str] = field(default_factory=list)
    removed_actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _fetch_spec_and_digest(url: str) -> tuple[dict, str]:
    """Fetch an OpenAPI spec from *url* and return ``(spec_dict, sha256_hex)``."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "yaml" in content_type or url.endswith((".yaml", ".yml")):
        spec = yaml.safe_load(response.text)
    else:
        spec = response.json()

    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return spec, digest


def _action_key(interface_alias: str, resource_alias: str, action_alias: str) -> str:
    """Dotted key for identifying an action."""
    return f"{interface_alias}.{resource_alias}.{action_alias}"


def _build_spec_action_set(generated: GeneratedSystem) -> dict[str, dict]:
    """Build ``{dotted_key: field_dict}`` from a GeneratedSystem."""
    actions = {}
    for iface in generated.interfaces:
        for res in iface.resources:
            for act in res.actions:
                key = _action_key(
                    iface.alias or iface.name,
                    res.alias or res.name,
                    act.alias or act.name,
                )
                actions[key] = {
                    "method": act.method,
                    "path": act.path,
                    "parameters_schema": act.parameters_schema,
                    "output_schema": act.output_schema,
                }
    return actions


def _build_db_action_set(system: System) -> dict[str, dict]:
    """Build ``{dotted_key: field_dict}`` from existing DB records."""
    actions = {}
    qs = Action.objects.filter(resource__interface__system=system).select_related("resource__interface")
    for act in qs:
        key = _action_key(
            act.resource.interface.alias,
            act.resource.alias,
            act.alias,
        )
        actions[key] = {
            "method": act.method,
            "path": act.path,
            "parameters_schema": act.parameters_schema,
            "output_schema": act.output_schema,
        }
    return actions


def check_for_updates(system: System, spec_url: str | None = None) -> bool:
    """
    Lightweight check — fetch spec and compare digest only, no parsing.

    Stores result in ``system.meta``:
        - ``refresh_pending``: True if spec changed
        - ``refresh_checked_at``: ISO timestamp of this check
        - ``refresh_pending_digest``: new digest (only when changed)

    Returns True if the spec has changed since last refresh.
    """
    url = spec_url or (system.meta or {}).get("openapi_spec_url")
    if not url:
        raise ValueError(f"No spec URL provided and system '{system.alias}' has no meta.openapi_spec_url configured.")

    _, new_digest = _fetch_spec_and_digest(url)
    old_digest = system.schema_digest or ""
    changed = old_digest != new_digest

    if not system.meta:
        system.meta = {}
    system.meta["refresh_pending"] = changed
    system.meta["refresh_checked_at"] = timezone.now().isoformat()
    if changed:
        system.meta["refresh_pending_digest"] = new_digest
    else:
        system.meta.pop("refresh_pending_digest", None)
    system.save(update_fields=["meta"])

    return changed


def refresh_adapter(
    system: System,
    spec_url: str | None = None,
    dry_run: bool = False,
) -> RefreshResult:
    """
    Re-fetch an OpenAPI spec and synchronise changes to the database.

    Args:
        system:   The System model instance to refresh.
        spec_url: Override URL (falls back to ``system.meta['openapi_spec_url']``).
        dry_run:  Parse and diff only — do not write to the database.

    Returns:
        RefreshResult with diff details.
    """
    url = spec_url or (system.meta or {}).get("openapi_spec_url")
    if not url:
        raise ValueError(f"No spec URL provided and system '{system.alias}' has no meta.openapi_spec_url configured.")

    old_digest = system.schema_digest or ""

    # Fetch & hash
    spec, new_digest = _fetch_spec_and_digest(url)

    # Fast path — nothing changed
    if old_digest == new_digest:
        return RefreshResult(
            system_alias=system.alias,
            spec_changed=False,
            old_digest=old_digest,
            new_digest=new_digest,
        )

    # Parse spec into GeneratedSystem
    generator = AdapterGenerator()
    generated = generator.from_openapi(
        spec=spec,
        system_name=system.name,
        system_alias=system.alias,
    )

    # Build diff
    spec_actions = _build_spec_action_set(generated)
    db_actions = _build_db_action_set(system)

    spec_keys = set(spec_actions)
    db_keys = set(db_actions)

    new_keys = sorted(spec_keys - db_keys)
    removed_keys = sorted(db_keys - spec_keys)
    common_keys = spec_keys & db_keys

    updated_keys = []
    unchanged_keys = []
    for key in sorted(common_keys):
        if spec_actions[key] != db_actions[key]:
            updated_keys.append(key)
        else:
            unchanged_keys.append(key)

    result = RefreshResult(
        system_alias=system.alias,
        spec_changed=True,
        old_digest=old_digest,
        new_digest=new_digest,
        new_actions=new_keys,
        updated_actions=updated_keys,
        unchanged_actions=unchanged_keys,
        removed_actions=removed_keys,
    )

    if dry_run:
        return result

    # Apply changes inside a transaction
    with transaction.atomic():
        generator.save_to_database(generated, account_id=None)

        system.schema_digest = new_digest
        if not system.meta:
            system.meta = {}
        system.meta["last_refreshed"] = timezone.now().isoformat()
        # Persist the spec URL if it was passed explicitly
        if spec_url:
            system.meta["openapi_spec_url"] = spec_url
        system.save(update_fields=["schema_digest", "meta"])

    logger.info(
        "Refreshed %s: +%d new, ~%d updated, =%d unchanged, -%d removed",
        system.alias,
        len(new_keys),
        len(updated_keys),
        len(unchanged_keys),
        len(removed_keys),
    )

    return result
