"""
Dataset Data Pointer API for MCP Agents.

Provides first-class dataset lifecycle management:
- create_dataset_query: Execute a system tool, store all results as dataset
- dataset_page: Cursor-based pagination through cached data
- dataset_agg: Group-by aggregation with metrics (count/sum/avg/min/max)
- dataset_sample: Sample rows (first/last/random/uniform)
- dataset_export: Export to CSV/JSON/JSONL, return presigned URL
- dataset_get: Metadata: schema, provenance, stats, row count
- dataset_close: Delete from S3, free resources
"""

import csv
import io
import json
import logging
import random
import re
import time
import uuid
from collections import defaultdict
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...config import get_settings
from ...models.systems import AccountSystem, Action, Interface, Resource, System

logger = logging.getLogger(__name__)

# S3 key prefix for dataset cache
S3_PREFIX = "datasets/"

# TTL for cached datasets (30 minutes)
DATASET_TTL_SECONDS = 1800

# Regex for datetime detection
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")


# ---------------------------------------------------------------------------
# S3 helpers (unchanged)
# ---------------------------------------------------------------------------


@lru_cache
def _get_s3_client():
    """Get S3 client configured from settings."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        region_name=settings.object_storage_region,
    )


def _get_bucket() -> str:
    return get_settings().object_storage_bucket


def _s3_key(dataset_id: str) -> str:
    return f"{S3_PREFIX}{dataset_id}.json"


def _is_enabled() -> bool:
    return get_settings().object_storage_enabled


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------


def _looks_like_datetime(value: Any) -> bool:
    """Check if a value looks like a datetime string."""
    if not isinstance(value, str):
        return False
    return bool(_DATETIME_RE.match(value))


def _looks_like_number(value: Any) -> bool:
    """Check if a value is numeric or a numeric string."""
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    return False


# ---------------------------------------------------------------------------
# Schema / stats helpers
# ---------------------------------------------------------------------------


def _infer_schema(items: list[dict], sample_size: int = 100) -> list[dict]:
    """Infer column schema from first N rows.

    Returns list of {name, type} where type is one of:
    boolean, number, datetime, string, null.
    """
    if not items or not isinstance(items[0], dict):
        return []

    sample = items[:sample_size]

    # Collect all column names across sample (preserving order from first row)
    seen = set()
    columns = []
    for row in sample:
        if isinstance(row, dict):
            for k in row:
                if k not in seen:
                    seen.add(k)
                    columns.append(k)

    schema = []
    for col in columns:
        # Gather non-None values for this column
        values = [row.get(col) for row in sample if isinstance(row, dict) and row.get(col) is not None]

        if not values:
            schema.append({"name": col, "type": "null"})
            continue

        # Check types of sampled values
        v = values[0]
        if isinstance(v, bool):
            col_type = "boolean"
        elif isinstance(v, (int, float)):
            col_type = "number"
        elif _looks_like_datetime(v):
            col_type = "datetime"
        elif _looks_like_number(v):
            col_type = "number"
        else:
            col_type = "string"

        schema.append({"name": col, "type": col_type})

    return schema


def _compute_stats(items: list[dict], schema: list[dict]) -> dict:
    """Compute per-column stats.

    Returns {row_count, columns: {col: {null_count, unique_count, min?, max?}}}.
    """
    row_count = len(items)
    col_stats: dict[str, dict] = {}

    for col_def in schema:
        col = col_def["name"]
        col_type = col_def["type"]

        values = [row.get(col) for row in items if isinstance(row, dict)]
        non_null = [v for v in values if v is not None]

        stats_entry: dict[str, Any] = {
            "null_count": len(values) - len(non_null),
            "unique_count": len({str(v) for v in non_null}),
        }

        if col_type == "number" and non_null:
            try:
                nums = [float(v) for v in non_null]
                stats_entry["min"] = min(nums)
                stats_entry["max"] = max(nums)
            except (ValueError, TypeError):
                pass

        col_stats[col] = stats_entry

    return {"row_count": row_count, "columns": col_stats}


def _sanitize_tool_name(name: str) -> str:
    """Sanitize tool name to be MCP-compliant (duplicated from systems.py to avoid circular import)."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    name = name.lower()
    return name


# ---------------------------------------------------------------------------
# Internal functions: store_dataset (enhanced) + _load_dataset (unchanged)
# ---------------------------------------------------------------------------


def store_dataset(
    account_id: int,
    items: list,
    source_info: dict,
) -> dict:
    """Store a dataset to S3 and return summary with pointer.

    Args:
        account_id: Owner account
        items: List of data items (dicts)
        source_info: Metadata about the source (system, tool, etc.)

    Returns:
        Summary dict with dataset_id, total_items, columns, sample, schema, stats
    """
    # Compute schema and stats up front
    schema = _infer_schema(items)
    stats = _compute_stats(items, schema)

    if not _is_enabled():
        logger.warning("Object storage not enabled, returning inline data")
        return {
            "dataset_id": None,
            "total_items": len(items),
            "columns": [s["name"] for s in schema],
            "sample": items[:3],
            "schema": schema,
            "stats": stats,
            "inline_data": items[:200],
            "truncated": len(items) > 200,
        }

    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"

    columns = [s["name"] for s in schema]
    sample = items[:3] if items else []

    # Build metadata + data payload
    payload = {
        "dataset_id": dataset_id,
        "account_id": account_id,
        "total_items": len(items),
        "columns": columns,
        "sample": sample,
        "schema": schema,
        "stats": stats,
        "source": source_info,
        "created_at": time.time(),
        "items": items,
    }

    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=_get_bucket(),
            Key=_s3_key(dataset_id),
            Body=json.dumps(payload, default=str).encode("utf-8"),
            ContentType="application/json",
            Metadata={
                "account_id": str(account_id),
                "created_at": str(int(time.time())),
            },
        )

        logger.info(f"Stored dataset {dataset_id}: {len(items)} items, {len(columns)} columns for account {account_id}")

        return {
            "dataset_id": dataset_id,
            "total_items": len(items),
            "columns": columns,
            "sample": sample,
            "schema": schema,
            "stats": stats,
            "source": source_info,
        }

    except Exception as e:
        logger.error(f"Failed to store dataset to S3: {e}")
        return {
            "dataset_id": None,
            "total_items": len(items),
            "columns": columns,
            "sample": sample,
            "schema": schema,
            "stats": stats,
            "inline_data": items[:200],
            "truncated": len(items) > 200,
            "storage_error": str(e),
        }


def _load_dataset(dataset_id: str, account_id: int) -> dict | None:
    """Load a dataset from S3, verifying ownership."""
    if not _is_enabled():
        return None

    try:
        s3 = _get_s3_client()
        response = s3.get_object(
            Bucket=_get_bucket(),
            Key=_s3_key(dataset_id),
        )
        payload = json.loads(response["Body"].read().decode("utf-8"))

        # Verify ownership
        if payload.get("account_id") != account_id:
            logger.warning(
                f"Dataset {dataset_id} access denied: owner={payload.get('account_id')}, requester={account_id}"
            )
            return None

        # Check TTL
        created_at = payload.get("created_at", 0)
        if time.time() - created_at > DATASET_TTL_SECONDS:
            # Expired — delete and return None
            try:
                s3.delete_object(Bucket=_get_bucket(), Key=_s3_key(dataset_id))
            except Exception:
                pass
            return None

        return payload

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        logger.error(f"Failed to load dataset {dataset_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load dataset {dataset_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# DB resolver: tool name → action_id
# ---------------------------------------------------------------------------


async def _resolve_tool_to_action_id(
    db: AsyncSession,
    tool_name: str,
    account_id: int,
    project_id: int | None = None,
) -> int | None:
    """Resolve a tool name like 'jira_issues_list' to an action_id.

    Queries Action → Resource → Interface → System → AccountSystem,
    reconstructs tool names and finds the match.
    """
    try:
        # Get enabled system IDs for this account (project-aware)
        enabled_stmt = (
            select(AccountSystem.system_id)
            .where(AccountSystem.account_id == account_id)
            .where(AccountSystem.is_enabled == True)  # noqa: E712
        )
        if project_id is not None:
            enabled_stmt = enabled_stmt.where(
                or_(AccountSystem.project_id == None, AccountSystem.project_id == project_id)  # noqa: E711
            )
        result = await db.execute(enabled_stmt)
        enabled_ids = [row[0] for row in result.fetchall()]

        if not enabled_ids:
            return None

        # Get all MCP-enabled actions for enabled systems
        actions_stmt = (
            select(Action)
            .join(Resource)
            .join(Interface)
            .join(System)
            .options(selectinload(Action.resource).selectinload(Resource.interface).selectinload(Interface.system))
            .where(System.id.in_(enabled_ids))
            .where(System.is_active == True)  # noqa: E712
            .where(Action.is_mcp_enabled == True)  # noqa: E712
        )
        result = await db.execute(actions_stmt)
        actions = result.scalars().all()

        for action in actions:
            resource = action.resource
            interface = resource.interface
            system = interface.system
            reconstructed = _sanitize_tool_name(
                f"{system.alias}_{resource.alias or resource.name}_{action.alias or action.name}"
            )
            if reconstructed == tool_name:
                return action.id

        return None

    except Exception as e:
        logger.error(f"Failed to resolve tool '{tool_name}': {e}")
        return None


# ---------------------------------------------------------------------------
# Data helpers: aggregate, sample, CSV export
# ---------------------------------------------------------------------------


def _aggregate(
    items: list[dict],
    group_by: list[str] | None,
    metrics: list[dict],
) -> list[dict]:
    """In-memory group-by aggregation.

    Args:
        items: list of row dicts
        group_by: column names to group by (None or [] for whole-dataset)
        metrics: list of {field, function} where function is count/sum/avg/min/max

    Returns:
        list of result dicts with group keys + computed metrics
    """
    group_by = group_by or []

    # Validate metrics
    valid_funcs = {"count", "sum", "avg", "min", "max"}
    for m in metrics:
        if m.get("function") not in valid_funcs:
            raise ValueError(f"Unknown metric function: {m.get('function')}. Supported: {', '.join(valid_funcs)}")

    # Build groups
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in items:
        if not isinstance(row, dict):
            continue
        key = tuple(row.get(col) for col in group_by) if group_by else ()
        groups[key].append(row)

    results = []
    for key, rows in groups.items():
        result: dict[str, Any] = {}
        # Add group-by columns
        for i, col in enumerate(group_by):
            result[col] = key[i]

        # Compute metrics
        for m in metrics:
            field = m.get("field")
            func = m["function"]
            alias = m.get("alias", f"{func}_{field}" if field else func)

            if func == "count":
                result[alias] = len(rows)
            else:
                # Extract numeric values
                vals = []
                for r in rows:
                    v = r.get(field)
                    if v is not None:
                        try:
                            vals.append(float(v))
                        except (ValueError, TypeError):
                            pass

                if not vals:
                    result[alias] = None
                elif func == "sum":
                    result[alias] = sum(vals)
                elif func == "avg":
                    result[alias] = sum(vals) / len(vals)
                elif func == "min":
                    result[alias] = min(vals)
                elif func == "max":
                    result[alias] = max(vals)

        results.append(result)

    return results


def _sample_rows(items: list[dict], n: int, strategy: str) -> list[dict]:
    """Sample rows from a dataset.

    Strategies:
    - first: first n rows
    - last: last n rows
    - random: random.sample
    - uniform: evenly spaced indices
    """
    if not items:
        return []
    n = min(n, len(items))

    if strategy == "first":
        return items[:n]
    elif strategy == "last":
        return items[-n:]
    elif strategy == "random":
        return random.sample(items, n)
    elif strategy == "uniform":
        if n >= len(items):
            return list(items)
        step = len(items) / n
        indices = [int(i * step) for i in range(n)]
        return [items[i] for i in indices]
    else:
        raise ValueError(f"Unknown sampling strategy: {strategy}. Supported: first, last, random, uniform")


def _to_csv(items: list[dict], columns: list[str] | None = None) -> bytes:
    """Convert list of dicts to CSV bytes."""
    if not items:
        return b""

    if not columns:
        # Collect all column names across all rows, preserving order from first row
        seen = set()
        columns = []
        for row in items:
            if isinstance(row, dict):
                for k in row:
                    if k not in seen:
                        seen.add(k)
                        columns.append(k)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in items:
        if isinstance(row, dict):
            writer.writerow(row)

    return output.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def handle_create_dataset_query(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Execute a system tool and store all results as a dataset."""
    account_id = ctx.get("account_id")
    db = ctx.get("db")
    tool_name = kwargs.get("tool", "")
    params = kwargs.get("params", {})

    if not db:
        return {"error": "Database session not available"}

    if not tool_name:
        return {"error": "Parameter 'tool' is required (the system tool name to execute)"}

    # Resolve tool name to action_id (project-aware)
    project_id = ctx.get("project_id")
    action_id = await _resolve_tool_to_action_id(db, tool_name, account_id, project_id=project_id)
    if not action_id:
        return {"error": f"Tool '{tool_name}' not found or not enabled for this account"}

    # Force fetch_all_pages
    params["fetch_all_pages"] = True

    # Execute via systems module (inline import to avoid circular)
    from .systems import execute_system_tool

    result = await execute_system_tool(
        db=db,
        action_id=action_id,
        account_id=account_id,
        params=params,
        get_external_id=ctx.get("get_external_id"),
        project_context=ctx.get("project_context"),
        project_id=project_id,
    )

    # If the action was non-paginated, result has "data" but no "dataset" key
    if "error" in result:
        return result

    if "dataset" in result:
        # Already stored as dataset by _execute_paginated_read
        ds = result["dataset"]
        return {
            "handle": ds.get("dataset_id"),
            "row_count": ds.get("total_items", 0),
            "schema": ds.get("schema", []),
            "stats": ds.get("stats", {}),
            "preview": ds.get("sample", []),
            "source": ds.get("source", {}),
        }

    # Non-paginated result — store the data as a new dataset
    data = result.get("data")
    if data is None:
        return {"error": "Tool returned no data"}

    # Normalize data to list of dicts
    if isinstance(data, dict):
        # Try to extract a list from common fields
        for field in ["content", "items", "data", "results", "records"]:
            if field in data and isinstance(data[field], list):
                data = data[field]
                break
        else:
            # Check for any list field
            found = False
            for _key, val in data.items():
                if isinstance(val, list):
                    data = val
                    found = True
                    break
            if not found:
                # Wrap single dict as list
                data = [data]

    if not isinstance(data, list):
        data = [data]

    ds = store_dataset(
        account_id=account_id,
        items=data,
        source_info={"tool": tool_name, "params": params},
    )

    return {
        "handle": ds.get("dataset_id"),
        "row_count": ds.get("total_items", 0),
        "schema": ds.get("schema", []),
        "stats": ds.get("stats", {}),
        "preview": ds.get("sample", []),
        "source": ds.get("source", {}),
    }


async def handle_dataset_page(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Cursor-based pagination through a cached dataset."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")
    cursor = kwargs.get("cursor", 0)
    limit = min(kwargs.get("limit", 100), 500)

    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    items = payload.get("items", [])
    page_items = items[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(items) else None

    return {
        "rows": page_items,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "total_rows": len(items),
    }


async def handle_dataset_agg(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Group-by aggregation with metrics."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")
    spec = kwargs.get("spec", {})

    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    group_by = spec.get("group_by")
    metrics = spec.get("metrics", [])

    if not metrics:
        return {"error": "spec.metrics is required (list of {field, function})"}

    items = payload.get("items", [])

    try:
        results = _aggregate(items, group_by, metrics)
    except ValueError as e:
        return {"error": str(e)}

    return {
        "results": results,
        "group_count": len(results),
        "total_rows_processed": len(items),
    }


async def handle_dataset_sample(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Sample rows from a dataset."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")
    n = kwargs.get("n", 10)
    strategy = kwargs.get("strategy", "first")

    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    items = payload.get("items", [])

    try:
        sampled = _sample_rows(items, n, strategy)
    except ValueError as e:
        return {"error": str(e)}

    return {
        "rows": sampled,
        "n": len(sampled),
        "strategy": strategy,
        "total_rows": len(items),
    }


async def handle_dataset_filter(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Search/filter rows in a dataset by field value."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")
    field_name = kwargs.get("field", "")
    operator = kwargs.get("operator", "contains")
    value = kwargs.get("value", "")
    limit = min(kwargs.get("limit", 200), 1000)

    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    columns = payload.get("columns", [])
    if columns and field_name not in columns:
        return {"error": f"Field '{field_name}' not found. Available: {columns}"}

    items = payload.get("items", [])
    matches = []

    for item in items:
        if not isinstance(item, dict):
            continue
        item_val = item.get(field_name)
        if item_val is None:
            continue

        match = False
        if operator == "contains":
            match = value.lower() in str(item_val).lower()
        elif operator == "equals":
            match = str(item_val) == value
        elif operator == "startswith":
            match = str(item_val).lower().startswith(value.lower())
        elif operator in ("gt", "lt", "gte", "lte"):
            try:
                num_val = float(item_val)
                num_target = float(value)
                if operator == "gt":
                    match = num_val > num_target
                elif operator == "lt":
                    match = num_val < num_target
                elif operator == "gte":
                    match = num_val >= num_target
                elif operator == "lte":
                    match = num_val <= num_target
            except (ValueError, TypeError):
                continue

        if match:
            matches.append(item)
            if len(matches) >= limit:
                break

    return {
        "rows": matches,
        "total_matches": len(matches),
        "truncated": len(matches) >= limit,
        "filter": {"field": field_name, "operator": operator, "value": value},
        "total_rows": len(items),
    }


async def handle_dataset_export(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Export dataset to CSV/JSON/JSONL and return presigned URL."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")
    fmt = kwargs.get("format", "csv").lower()

    if fmt not in ("csv", "json", "jsonl"):
        return {"error": f"Unsupported format: {fmt}. Supported: csv, json, jsonl"}

    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    items = payload.get("items", [])
    columns = payload.get("columns", [])

    # Convert to bytes
    if fmt == "csv":
        body = _to_csv(items, columns or None)
        content_type = "text/csv"
    elif fmt == "json":
        body = json.dumps(items, default=str, indent=2).encode("utf-8")
        content_type = "application/json"
    else:  # jsonl
        lines = [json.dumps(row, default=str) for row in items]
        body = "\n".join(lines).encode("utf-8")
        content_type = "application/x-ndjson"

    ext = fmt
    export_key = f"{S3_PREFIX}exports/{handle}.{ext}"

    if not _is_enabled():
        # Fallback: return inline data (truncated)
        return {
            "format": fmt,
            "size_bytes": len(body),
            "row_count": len(items),
            "inline_data": body[:10000].decode("utf-8", errors="replace"),
            "truncated": len(body) > 10000,
        }

    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=_get_bucket(),
            Key=export_key,
            Body=body,
            ContentType=content_type,
            Metadata={"account_id": str(account_id), "source_dataset": handle},
        )

        # Generate presigned URL (1 hour)
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": _get_bucket(), "Key": export_key},
            ExpiresIn=3600,
        )

        return {
            "format": fmt,
            "size_bytes": len(body),
            "row_count": len(items),
            "url": url,
            "expires_in": 3600,
        }

    except Exception as e:
        logger.error(f"Failed to export dataset {handle}: {e}")
        return {"error": f"Export failed: {e}"}


async def handle_dataset_get(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Get dataset metadata: schema, provenance, stats, row count."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")

    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    created_at = payload.get("created_at", time.time())
    age = time.time() - created_at
    ttl_remaining = max(0, DATASET_TTL_SECONDS - age)

    return {
        "handle": handle,
        "row_count": payload.get("total_items", len(payload.get("items", []))),
        "columns": payload.get("columns", []),
        "schema": payload.get("schema", []),
        "stats": payload.get("stats", {}),
        "source": payload.get("source", {}),
        "age_seconds": int(age),
        "ttl_remaining_seconds": int(ttl_remaining),
    }


async def handle_dataset_close(ctx: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Delete dataset from S3, free resources."""
    account_id = ctx.get("account_id")
    handle = kwargs.get("handle", "")

    # Verify ownership first
    payload = _load_dataset(handle, account_id)
    if not payload:
        return {"error": f"Dataset '{handle}' not found or expired"}

    if not _is_enabled():
        return {"error": "Object storage not enabled"}

    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()

        # Delete the dataset object
        s3.delete_object(Bucket=bucket, Key=_s3_key(handle))

        # Delete any export files
        for ext in ("csv", "json", "jsonl"):
            try:
                s3.delete_object(
                    Bucket=bucket,
                    Key=f"{S3_PREFIX}exports/{handle}.{ext}",
                )
            except Exception:
                pass

        return {"deleted": True, "handle": handle}

    except Exception as e:
        logger.error(f"Failed to delete dataset {handle}: {e}")
        return {"error": f"Delete failed: {e}"}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def get_dataset_tools() -> list[dict[str, Any]]:
    """Return MCP tool definitions for dataset operations."""
    return [
        {
            "name": "create_dataset_query",
            "description": (
                "Execute a system tool and store ALL results as a dataset pointer. "
                "Returns a handle you can use with dataset_page, dataset_filter, "
                "dataset_agg, dataset_sample, dataset_export, dataset_get, and dataset_close. "
                "Use this when you need to work with full result sets."
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "description": (
                            "Name of the system tool to execute (e.g. 'jira_issues_list', 'hubspot_contacts_list')"
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": "Parameters to pass to the system tool",
                        "default": {},
                    },
                },
                "required": ["tool"],
            },
            "handler": handle_create_dataset_query,
        },
        {
            "name": "dataset_page",
            "description": (
                "Get a page of rows from a cached dataset using cursor-based pagination. "
                "Returns rows starting at the cursor position."
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle (e.g. ds_abc123def456)",
                    },
                    "cursor": {
                        "type": "integer",
                        "description": "Row offset to start from (default: 0)",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default: 100, max: 500)",
                        "default": 100,
                    },
                },
                "required": ["handle"],
            },
            "handler": handle_dataset_page,
        },
        {
            "name": "dataset_agg",
            "description": (
                "Run group-by aggregation on a dataset. "
                "Supports metrics: count, sum, avg, min, max. "
                'Example spec: {"group_by": ["status"], "metrics": [{"field": "amount", "function": "sum"}]}'
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle",
                    },
                    "spec": {
                        "type": "object",
                        "description": "Aggregation spec with group_by (optional list of columns) and metrics (list of {field, function, alias?})",
                        "properties": {
                            "group_by": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Columns to group by (omit for whole-dataset aggregation)",
                            },
                            "metrics": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "field": {
                                            "type": "string",
                                            "description": "Column to aggregate (not needed for count)",
                                        },
                                        "function": {
                                            "type": "string",
                                            "enum": ["count", "sum", "avg", "min", "max"],
                                            "description": "Aggregation function",
                                        },
                                        "alias": {
                                            "type": "string",
                                            "description": "Output column name (default: function_field)",
                                        },
                                    },
                                    "required": ["function"],
                                },
                                "description": "Metrics to compute",
                            },
                        },
                        "required": ["metrics"],
                    },
                },
                "required": ["handle", "spec"],
            },
            "handler": handle_dataset_agg,
        },
        {
            "name": "dataset_sample",
            "description": ("Sample rows from a dataset. Strategies: first, last, random, uniform (evenly spaced)."),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of rows to sample (default: 10)",
                        "default": 10,
                    },
                    "strategy": {
                        "type": "string",
                        "description": "Sampling strategy",
                        "enum": ["first", "last", "random", "uniform"],
                        "default": "first",
                    },
                },
                "required": ["handle"],
            },
            "handler": handle_dataset_sample,
        },
        {
            "name": "dataset_filter",
            "description": (
                "Search/filter rows in a dataset by field value. "
                "Use to find specific items by name, status, or other fields. "
                "Supports: contains (case-insensitive substring), equals, startswith, gt, lt, gte, lte."
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle",
                    },
                    "field": {
                        "type": "string",
                        "description": "Field name to search/filter on (e.g. 'name', 'summary', 'status')",
                    },
                    "operator": {
                        "type": "string",
                        "description": "Filter operator",
                        "enum": ["contains", "equals", "startswith", "gt", "lt", "gte", "lte"],
                        "default": "contains",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to search for or compare against",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default: 200, max: 1000)",
                        "default": 200,
                    },
                },
                "required": ["handle", "field", "value"],
            },
            "handler": handle_dataset_filter,
        },
        {
            "name": "dataset_export",
            "description": (
                "Export a dataset to CSV, JSON, or JSONL format. Returns a presigned download URL valid for 1 hour."
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle",
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format",
                        "enum": ["csv", "json", "jsonl"],
                        "default": "csv",
                    },
                },
                "required": ["handle"],
            },
            "handler": handle_dataset_export,
        },
        {
            "name": "dataset_get",
            "description": (
                "Get metadata about a dataset: schema (column types), "
                "provenance (source tool and params), stats (per-column), "
                "row count, age, and TTL remaining."
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle (e.g. ds_abc123def456)",
                    },
                },
                "required": ["handle"],
            },
            "handler": handle_dataset_get,
        },
        {
            "name": "dataset_close",
            "description": (
                "Delete a dataset from storage and free resources. Use when done working with a dataset to clean up."
            ),
            "tool_type": "dataset",
            "input_schema": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "Dataset handle to delete",
                    },
                },
                "required": ["handle"],
            },
            "handler": handle_dataset_close,
        },
    ]
