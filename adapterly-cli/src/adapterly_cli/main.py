"""Adapterly CLI — command-line client for Adapterly MCP Tool Gateway.

Usage:
    adapterly config --url https://adapterly.ai --key ak_live_xxx
    adapterly tools
    adapterly tools --search projects
    adapterly call my_system_projects_list
    adapterly call my_system_items_list --param page=1
    adapterly call my_system_projects_get --param id=abc-123 --output json
"""

import json
import sys

import click

from .client import AdapterlyClient
from .config import get_key, get_url, load_config, save_config


def _get_client() -> AdapterlyClient:
    """Create client from config, exit if not configured."""
    url = get_url()
    key = get_key()
    if not url or not key:
        click.echo("Not configured. Run: adapterly config --url <URL> --key <KEY>", err=True)
        sys.exit(1)
    return AdapterlyClient(url, key)


@click.group()
@click.version_option()
def cli():
    """Adapterly CLI — call MCP adapter tools from the command line."""


@cli.command()
@click.option("--url", required=True, help="Adapterly API base URL (e.g. https://adapterly.ai)")
@click.option("--key", required=True, help="API key (ak_live_...)")
def config(url, key):
    """Save connection settings to ~/.adapterly/config.json."""
    cfg = load_config()
    cfg["url"] = url.rstrip("/")
    cfg["key"] = key
    save_config(cfg)
    click.echo(f"Saved: {url}")


@cli.command()
@click.option("--search", "-s", default=None, help="Filter tools by name or description")
@click.option("--format", "fmt", type=click.Choice(["simple", "mcp"]), default="simple")
def tools(search, fmt):
    """List available tools."""
    client = _get_client()
    try:
        result = client.list_tools(search=search, fmt=fmt)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    tools_list = result.get("tools", [])
    if not tools_list:
        click.echo("No tools found.")
        return

    if fmt == "mcp":
        click.echo(json.dumps(tools_list, indent=2))
        return

    # Table output
    max_name = max(len(t["name"]) for t in tools_list)
    for t in tools_list:
        desc = t.get("description", "")
        if len(desc) > 80:
            desc = desc[:77] + "..."
        click.echo(f"  {t['name']:<{max_name}}  {desc}")
    click.echo(f"\n{len(tools_list)} tools")


@cli.command()
@click.argument("tool_name")
@click.option("--param", "-p", multiple=True, help="Parameter as key=value (repeatable)")
@click.option("--json-input", "-j", default=None, help="Full JSON parameters as string")
@click.option("--output", "-o", type=click.Choice(["json", "pretty", "raw"]), default="pretty")
def call(tool_name, param, json_input, output):
    """Call a tool by name.

    Examples:
        adapterly call my_system_projects_list
        adapterly call my_system_items_list -p page=1
        adapterly call my_system_projects_get -p id=abc-123
        adapterly call my_tool -j '{"complex": {"nested": true}}'
    """
    # Build arguments
    if json_input:
        try:
            arguments = json.loads(json_input)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid JSON: {e}", err=True)
            sys.exit(1)
    else:
        arguments = {}
        for p in param:
            if "=" not in p:
                click.echo(f"Invalid param (use key=value): {p}", err=True)
                sys.exit(1)
            k, v = p.split("=", 1)
            # Try to parse as number/bool/null
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass  # keep as string
            arguments[k] = v

    client = _get_client()
    try:
        result = client.call_tool(tool_name, arguments)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not result.get("success", False):
        click.echo(f"Error: {result.get('error', 'Unknown error')}", err=True)
        sys.exit(1)

    data = result.get("data")

    if output == "raw":
        if isinstance(data, str):
            click.echo(data)
        else:
            click.echo(json.dumps(data, default=str))
    elif output == "json":
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        # Pretty: auto-detect and format
        _pretty_print(data)


def _pretty_print(data):
    """Pretty-print tool result."""
    if isinstance(data, str):
        click.echo(data)
    elif isinstance(data, list):
        if not data:
            click.echo("(empty list)")
            return
        # Print as table if items are dicts
        if isinstance(data[0], dict):
            keys = list(data[0].keys())[:6]  # Max 6 columns
            widths = {k: max(len(k), max(len(str(item.get(k, ""))[:40]) for item in data)) for k in keys}
            # Header
            header = "  ".join(k.ljust(widths[k]) for k in keys)
            click.echo(header)
            click.echo("-" * len(header))
            # Rows
            for item in data:
                row = "  ".join(str(item.get(k, ""))[:40].ljust(widths[k]) for k in keys)
                click.echo(row)
            click.echo(f"\n{len(data)} items")
        else:
            for item in data:
                click.echo(f"  {item}")
    elif isinstance(data, dict):
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        click.echo(str(data))


if __name__ == "__main__":
    cli()
