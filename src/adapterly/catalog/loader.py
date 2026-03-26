"""Load integration specs from catalog JSON files into the database."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from ..database import get_session_factory
from ..models.integration import Integration, Tool

logger = logging.getLogger(__name__)

SPECS_DIR = Path(__file__).parent / "specs"


async def load_catalog():
    """Load all JSON specs from the catalog directory."""
    if not SPECS_DIR.exists():
        logger.info("No catalog specs directory found, skipping")
        return

    specs = list(SPECS_DIR.glob("*.json"))
    if not specs:
        logger.info("No catalog specs found")
        return

    factory = get_session_factory()
    async with factory() as db:
        for spec_path in specs:
            try:
                await _load_spec(db, spec_path)
            except Exception as e:
                logger.error(f"Failed to load spec {spec_path.name}: {e}")
        await db.commit()

    logger.info(f"Loaded {len(specs)} catalog specs")


async def _load_spec(db, spec_path: Path):
    """Load a single integration spec."""
    with open(spec_path) as f:
        spec = json.load(f)

    slug = spec["slug"]

    # Check if already exists
    result = await db.execute(
        select(Integration).where(Integration.slug == slug, Integration.scope == "public")
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing
        existing.name = spec.get("name", existing.name)
        existing.description = spec.get("description", existing.description)
        existing.category = spec.get("category", existing.category)
        existing.base_url = spec.get("base_url", existing.base_url)
        existing.auth_config = spec.get("auth_config", existing.auth_config)
        existing.variables = spec.get("variables", existing.variables)
        integration = existing
    else:
        integration = Integration(
            slug=slug,
            name=spec["name"],
            description=spec.get("description", ""),
            category=spec.get("category", "other"),
            base_url=spec.get("base_url", ""),
            auth_config=spec.get("auth_config", {}),
            variables=spec.get("variables", {}),
            scope="public",
        )
        db.add(integration)
        await db.flush()

    # Sync tools
    existing_tools = {t.slug: t for t in (await db.execute(
        select(Tool).where(Tool.integration_id == integration.id)
    )).scalars().all()}

    for tool_spec in spec.get("tools", []):
        tool_slug = tool_spec["slug"]
        if tool_slug in existing_tools:
            tool = existing_tools[tool_slug]
            tool.name = tool_spec.get("name", tool.name)
            tool.description = tool_spec.get("description", tool.description)
            tool.method = tool_spec.get("method", tool.method)
            tool.path = tool_spec.get("path", tool.path)
            tool.parameters_schema = tool_spec.get("parameters_schema", tool.parameters_schema)
            tool.pagination = tool_spec.get("pagination", tool.pagination)
            tool.tool_type = tool_spec.get("tool_type", tool.tool_type)
            tool.headers = tool_spec.get("headers", tool.headers)
        else:
            tool = Tool(
                integration_id=integration.id,
                slug=tool_slug,
                name=tool_spec.get("name", tool_slug),
                description=tool_spec.get("description", ""),
                method=tool_spec.get("method", "GET"),
                path=tool_spec.get("path", ""),
                parameters_schema=tool_spec.get("parameters_schema", {}),
                pagination=tool_spec.get("pagination", {}),
                tool_type=tool_spec.get("tool_type", "read"),
                headers=tool_spec.get("headers", {}),
            )
            db.add(tool)

    logger.info(f"Loaded integration: {slug} ({len(spec.get('tools', []))} tools)")
