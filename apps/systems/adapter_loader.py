"""
YAML-based adapter loader.

Discovers adapter YAML files under adapters/<industry>/<system>.yaml,
parses them, and upserts System/Interface/Resource/Action/AuthenticationStep
records using update_or_create for idempotency.

Usage:
    from apps.systems.adapter_loader import discover_adapter_files, load_adapter_file

    for path in discover_adapter_files():
        load_adapter_file(path)
"""

import logging
from pathlib import Path
from typing import Optional

import yaml
from django.db import transaction

from apps.systems.models import (
    Action,
    AuthenticationStep,
    Interface,
    Resource,
    System,
)

logger = logging.getLogger(__name__)

ADAPTERS_DIR = Path(__file__).resolve().parent.parent.parent / "adapters"

REQUIRED_SYSTEM_FIELDS = {"alias", "name", "display_name", "description", "system_type"}


def discover_adapter_files(industry: str | None = None) -> list[Path]:
    """
    Find all adapter YAML files under adapters/**/*.yaml.
    Skips files starting with underscore (e.g. _template.yaml).

    Args:
        industry: If given, only return files under adapters/<industry>/.

    Returns:
        Sorted list of Path objects.
    """
    if not ADAPTERS_DIR.is_dir():
        logger.warning("Adapters directory not found: %s", ADAPTERS_DIR)
        return []

    if industry:
        search_dir = ADAPTERS_DIR / industry
        if not search_dir.is_dir():
            logger.warning("Industry directory not found: %s", search_dir)
            return []
        pattern = "*.yaml"
    else:
        search_dir = ADAPTERS_DIR
        pattern = "**/*.yaml"

    files = [p for p in sorted(search_dir.glob(pattern)) if p.is_file() and not p.name.startswith("_")]
    return files


def parse_adapter_file(path: Path) -> dict:
    """
    Load and validate an adapter YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If required fields are missing.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data).__name__}")

    system = data.get("system")
    if not system:
        raise ValueError(f"{path}: missing top-level 'system' key")

    missing = REQUIRED_SYSTEM_FIELDS - set(system.keys())
    if missing:
        raise ValueError(f"{path}: system missing required fields: {', '.join(sorted(missing))}")

    interfaces = data.get("interfaces", [])
    for iface in interfaces:
        if not iface.get("alias"):
            raise ValueError(f"{path}: interface missing 'alias'")
        for res in iface.get("resources", []):
            if not res.get("alias"):
                raise ValueError(f"{path}: resource missing 'alias'")
            for act in res.get("actions", []):
                if not act.get("alias"):
                    raise ValueError(f"{path}: action missing 'alias'")
                if not act.get("method"):
                    raise ValueError(f"{path}: action '{act.get('alias')}' missing 'method'")

    return data


@transaction.atomic
def load_adapter(data: dict, dry_run: bool = False) -> Optional["System"]:
    """
    Upsert a full adapter definition into the database.

    Uses update_or_create keyed on alias (matching adapter_generator.py pattern).

    Args:
        data: Parsed adapter dict (from parse_adapter_file).
        dry_run: If True, validate only — rolls back the transaction.

    Returns:
        The System instance (None in dry-run mode).
    """
    sid = transaction.savepoint()

    try:
        db_system = _load_system(data["system"])
        _load_interfaces(db_system, data.get("interfaces", []))
        _load_auth_steps(db_system, data.get("auth_steps", []))

        if dry_run:
            transaction.savepoint_rollback(sid)
            return None

        transaction.savepoint_commit(sid)
        return db_system

    except Exception:
        transaction.savepoint_rollback(sid)
        raise


def _load_system(system_data: dict) -> System:
    """Create or update the System record."""
    defaults = {
        "name": system_data["name"],
        "display_name": system_data["display_name"],
        "description": system_data["description"],
        "system_type": system_data["system_type"],
        "is_active": True,
    }

    # Optional fields
    for field in ("icon", "website_url", "docs_url"):
        if field in system_data:
            defaults[field] = system_data[field]

    if "variables" in system_data:
        defaults["variables"] = system_data["variables"]

    if "meta" in system_data:
        defaults["meta"] = system_data["meta"]

    db_system, created = System.objects.update_or_create(
        alias=system_data["alias"],
        defaults=defaults,
    )
    action = "Created" if created else "Updated"
    logger.info("%s system: %s", action, db_system.alias)
    return db_system


def _load_interfaces(db_system: System, interfaces: list[dict]) -> None:
    """Create or update interfaces, resources, and actions."""
    for iface_data in interfaces:
        iface_defaults = {
            "name": iface_data.get("name", iface_data["alias"]),
            "type": iface_data.get("type", "API"),
        }

        for field in ("base_url", "auth", "requires_browser", "rate_limits"):
            if field in iface_data:
                iface_defaults[field] = iface_data[field]

        db_interface, _ = Interface.objects.update_or_create(
            system=db_system,
            alias=iface_data["alias"],
            defaults=iface_defaults,
        )

        _load_resources(db_interface, iface_data.get("resources", []))


def _load_resources(db_interface: Interface, resources: list[dict]) -> None:
    """Create or update resources and their actions."""
    for res_data in resources:
        db_resource, _ = Resource.objects.update_or_create(
            interface=db_interface,
            alias=res_data["alias"],
            defaults={
                "name": res_data.get("name", res_data["alias"]),
                "description": res_data.get("description", ""),
            },
        )

        for act_data in res_data.get("actions", []):
            act_defaults = {
                "name": act_data.get("name", act_data["alias"]),
                "method": act_data["method"],
                "description": act_data.get("description", ""),
            }

            if "path" in act_data:
                act_defaults["path"] = act_data["path"]

            if "parameters_schema" in act_data:
                act_defaults["parameters_schema"] = act_data["parameters_schema"]

            if "output_schema" in act_data:
                act_defaults["output_schema"] = act_data["output_schema"]

            if "headers" in act_data:
                act_defaults["headers"] = act_data["headers"]

            Action.objects.update_or_create(
                resource=db_resource,
                alias=act_data["alias"],
                defaults=act_defaults,
            )


def _load_auth_steps(db_system: System, auth_steps: list[dict]) -> None:
    """Create or update authentication steps."""
    _AUTH_STEP_FIELDS = (
        "description",
        "input_fields",
        "base_url",
        "is_required",
        "is_optional",
        "timeout_seconds",
        "validation_rules",
        "success_message",
        "failure_message",
    )

    for step_data in auth_steps:
        defaults = {
            "step_type": step_data["step_type"],
            "step_name": step_data["step_name"],
        }
        for field in _AUTH_STEP_FIELDS:
            if field in step_data:
                defaults[field] = step_data[field]

        AuthenticationStep.objects.update_or_create(
            system=db_system,
            step_order=step_data.get("step_order", 1),
            defaults=defaults,
        )


def load_adapter_file(path: Path, dry_run: bool = False) -> System | None:
    """
    Parse and load a single adapter file.

    Convenience wrapper combining parse_adapter_file + load_adapter.

    Args:
        path: Path to the YAML file.
        dry_run: If True, validate only.

    Returns:
        The System instance (None in dry-run mode).
    """
    data = parse_adapter_file(path)
    return load_adapter(data, dry_run=dry_run)
