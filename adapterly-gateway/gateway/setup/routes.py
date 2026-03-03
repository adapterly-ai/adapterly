"""
Setup wizard — first-time gateway configuration via browser.

Steps:
1. Register: Enter Control Plane URL + Registration Token
2. Integrations: Configure credentials for each synced system
3. Done: Show MCP endpoint + API key + copy-paste configs
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from html import escape

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from gateway_core.crypto import configure_secret_key, encrypt_value
from gateway_core.executor import _get_auth_headers
from gateway_core.models import AccountSystem, Interface, MCPApiKey, System

from .._env_writer import write_env_values
from ..config import get_settings, reload_settings
from ..database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])


# ---------------------------------------------------------------------------
# Step 1: Welcome / Register
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def setup_welcome(request: Request):
    settings = get_settings()
    if settings.is_registered:
        return RedirectResponse(url="/setup/integrations", status_code=303)
    return HTMLResponse(_render_step1())


@router.post("/register")
async def setup_register(
    request: Request,
    control_plane_url: str = Form(...),
    registration_token: str = Form(...),
    gateway_name: str = Form(""),
):
    """Register with control plane, save credentials, trigger initial sync."""
    url = f"{control_plane_url.rstrip('/')}/gateway-sync/v1/register"
    headers = {"Authorization": f"Bearer {registration_token}"}
    body = {}
    if gateway_name:
        body["name"] = gateway_name

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=body, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        error_msg = f"Registration failed: HTTP {e.response.status_code}"
        try:
            detail = e.response.json()
            error_msg += f" — {detail}"
        except Exception:
            pass
        return HTMLResponse(_render_step1(error=error_msg), status_code=400)
    except Exception as e:
        return HTMLResponse(_render_step1(error=f"Connection failed: {e}"), status_code=400)

    gateway_id = data["gateway_id"]
    gateway_secret = data["gateway_secret"]

    # Write to .env
    write_env_values(
        {
            "GATEWAY_GATEWAY_ID": gateway_id,
            "GATEWAY_GATEWAY_SECRET": gateway_secret,
            "GATEWAY_CONTROL_PLANE_URL": control_plane_url,
        }
    )

    # Also set in environment so reload picks them up
    os.environ["GATEWAY_GATEWAY_ID"] = gateway_id
    os.environ["GATEWAY_GATEWAY_SECRET"] = gateway_secret
    os.environ["GATEWAY_CONTROL_PLANE_URL"] = control_plane_url

    # Reload settings
    new_settings = reload_settings()
    configure_secret_key(new_settings.secret_key)

    # Trigger immediate spec + key sync
    try:
        from ..sync.key_sync import sync_keys_once
        from ..sync.spec_sync import sync_specs_once

        await sync_specs_once()
        await sync_keys_once()

        # Start background sync loops
        from ..reporting.audit_reporter import audit_push_loop
        from ..reporting.health_reporter import health_push_loop
        from ..sync.key_sync import key_sync_loop
        from ..sync.spec_sync import spec_sync_loop

        asyncio.create_task(spec_sync_loop())
        asyncio.create_task(key_sync_loop())
        asyncio.create_task(audit_push_loop())
        asyncio.create_task(health_push_loop())
    except Exception as e:
        logger.warning(f"Initial sync failed (non-fatal): {e}")

    return RedirectResponse(url="/setup/integrations", status_code=303)


# ---------------------------------------------------------------------------
# Step 2: Integrations
# ---------------------------------------------------------------------------


@router.get("/integrations", response_class=HTMLResponse)
async def setup_integrations(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.is_registered:
        return RedirectResponse(url="/setup/", status_code=303)

    stmt = (
        select(System)
        .where(System.is_active == True)  # noqa: E712
        .order_by(System.display_name)
    )
    result = await db.execute(stmt)
    systems = result.scalars().all()

    cred_stmt = select(AccountSystem).where(AccountSystem.is_enabled == True)  # noqa: E712
    cred_result = await db.execute(cred_stmt)
    credentials = cred_result.scalars().all()
    cred_map = {c.system_id: c for c in credentials}

    return HTMLResponse(_render_step2(systems, cred_map))


@router.get("/connect/{system_id}", response_class=HTMLResponse)
async def setup_connect_form(request: Request, system_id: int, db: AsyncSession = Depends(get_db)):
    system = await db.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    from ..admin.credential_schema import get_credential_fields

    fields = await get_credential_fields(system, db)

    stmt = (
        select(AccountSystem).where(AccountSystem.system_id == system_id).where(AccountSystem.is_enabled == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    return HTMLResponse(_render_connect_form(system, fields, cred))


@router.post("/connect/{system_id}")
async def setup_connect_save(request: Request, system_id: int, db: AsyncSession = Depends(get_db)):
    system = await db.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    form_data = await request.form()

    stmt = select(AccountSystem).where(AccountSystem.system_id == system_id)
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    if not cred:
        cred = AccountSystem(
            account_id=1,
            system_id=system_id,
            is_enabled=True,
        )
        db.add(cred)

    # Map form fields to AccountSystem columns
    field_to_column = {
        "username": "username",
        "password": "password",
        "api_key": "api_key",
        "token": "token",
        "client_id": "client_id",
        "client_secret": "client_secret",
    }
    sensitive_columns = {"password", "api_key", "token", "client_secret"}

    for field_name, col_name in field_to_column.items():
        value = form_data.get(field_name, "")
        if value:
            if col_name in sensitive_columns:
                setattr(cred, col_name, encrypt_value(value))
            else:
                setattr(cred, col_name, value)

    cred.updated_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse(url="/setup/integrations", status_code=303)


@router.post("/test/{system_id}")
async def setup_test_connection(request: Request, system_id: int, db: AsyncSession = Depends(get_db)):
    """Test connection for a system (same logic as admin test)."""
    system = await db.get(System, system_id)
    if not system:
        return JSONResponse({"success": False, "message": "System not found"}, status_code=404)

    stmt = (
        select(AccountSystem)
        .options(selectinload(AccountSystem.system))
        .where(AccountSystem.system_id == system_id)
        .where(AccountSystem.is_enabled == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    account_system = result.scalar_one_or_none()

    if not account_system:
        return JSONResponse({"success": False, "message": "No credentials configured"})

    iface_stmt = select(Interface).where(Interface.system_id == system_id).limit(1)
    iface_result = await db.execute(iface_stmt)
    interface = iface_result.scalar_one_or_none()

    if not interface:
        return JSONResponse({"success": False, "message": "No interface found"})

    try:
        auth_headers = await _get_auth_headers(account_system, interface, db)
        if not auth_headers:
            account_system.last_error = "Authentication failed — no headers returned"
            await db.commit()
            return JSONResponse({"success": False, "message": "Authentication failed. Check credentials."})

        account_system.is_verified = True
        account_system.last_verified_at = datetime.now(timezone.utc)
        account_system.last_error = None
        await db.commit()

        return JSONResponse({"success": True, "message": f"Connected to {system.display_name} successfully."})

    except Exception as e:
        account_system.last_error = str(e)
        await db.commit()
        return JSONResponse({"success": False, "message": f"Connection failed: {e}"})


# ---------------------------------------------------------------------------
# Step 3: Done
# ---------------------------------------------------------------------------


@router.get("/done", response_class=HTMLResponse)
async def setup_done(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.is_registered:
        return RedirectResponse(url="/setup/", status_code=303)

    # Get first active API key
    stmt = select(MCPApiKey).where(MCPApiKey.is_active == True).limit(1)  # noqa: E712
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    host = request.headers.get("host", f"localhost:{settings.port}")
    scheme = request.url.scheme

    return HTMLResponse(_render_step3(host, scheme, api_key))


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _setup_base_html(title: str, content: str, step: int = 1) -> str:
    steps = [
        ("Register", 1),
        ("Connect", 2),
        ("Done", 3),
    ]
    steps_html = ""
    for label, num in steps:
        cls = "active" if num == step else ("done" if num < step else "")
        steps_html += f'<div class="step {cls}"><span class="step-num">{num}</span> {label}</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>{title} — Adapterly Gateway Setup</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f0f2f5; color: #333; line-height: 1.6; }}
        .header {{ background: #1a1a2e; color: white; padding: 20px 0; text-align: center; }}
        .header h1 {{ font-size: 20px; font-weight: 500; }}
        .header .subtitle {{ color: #8888aa; font-size: 13px; margin-top: 4px; }}
        .steps {{ display: flex; justify-content: center; gap: 32px; padding: 24px 0;
                  background: white; border-bottom: 1px solid #e0e0e0; }}
        .step {{ display: flex; align-items: center; gap: 8px; color: #999; font-size: 14px; }}
        .step.active {{ color: #4361ee; font-weight: 600; }}
        .step.done {{ color: #28a745; }}
        .step-num {{ width: 28px; height: 28px; border-radius: 50%; border: 2px solid #ddd;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 13px; font-weight: 600; }}
        .step.active .step-num {{ border-color: #4361ee; background: #4361ee; color: white; }}
        .step.done .step-num {{ border-color: #28a745; background: #28a745; color: white; }}
        .container {{ max-width: 640px; margin: 32px auto; padding: 0 20px; }}
        .card {{ background: white; border-radius: 8px; padding: 24px; margin-bottom: 16px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
        .btn {{ display: inline-block; padding: 10px 20px; border: none; border-radius: 6px;
               cursor: pointer; font-size: 14px; text-decoration: none; font-weight: 500; }}
        .btn-primary {{ background: #4361ee; color: white; }}
        .btn-primary:hover {{ background: #3451de; }}
        .btn-success {{ background: #28a745; color: white; }}
        .btn-outline {{ background: transparent; color: #4361ee; border: 1px solid #4361ee; }}
        .btn-sm {{ padding: 6px 14px; font-size: 13px; }}
        input[type=text], input[type=password], input[type=url] {{
            width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 6px;
            margin-bottom: 16px; font-size: 14px; }}
        input:focus {{ outline: none; border-color: #4361ee; box-shadow: 0 0 0 3px rgba(67,97,238,0.1); }}
        label {{ display: block; font-weight: 600; margin-bottom: 6px; font-size: 14px; }}
        .label-hint {{ font-weight: 400; color: #888; font-size: 12px; }}
        .error {{ background: #fff5f5; color: #c53030; padding: 12px 16px; border-radius: 6px;
                 margin-bottom: 16px; border: 1px solid #fed7d7; font-size: 14px; }}
        .success {{ background: #f0fff4; color: #22543d; padding: 12px 16px; border-radius: 6px;
                   margin-bottom: 16px; border: 1px solid #c6f6d5; font-size: 14px; }}
        .system-row {{ display: flex; justify-content: space-between; align-items: center;
                      padding: 16px 0; border-bottom: 1px solid #f0f0f0; }}
        .system-row:last-child {{ border-bottom: none; }}
        .status {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px;
                  font-weight: 500; }}
        .status-ok {{ background: #d4edda; color: #155724; }}
        .status-none {{ background: #f8d7da; color: #721c24; }}
        .status-verified {{ background: #cce5ff; color: #004085; }}
        pre {{ background: #1e1e2e; color: #cdd6f4; padding: 16px; border-radius: 6px;
              overflow-x: auto; font-size: 13px; line-height: 1.5; position: relative; }}
        .copy-btn {{ position: absolute; top: 8px; right: 8px; background: #45475a; color: #cdd6f4;
                    border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer;
                    font-size: 12px; }}
        .copy-btn:hover {{ background: #585b70; }}
        .flex {{ display: flex; gap: 8px; align-items: center; }}
        .test-result {{ margin-top: 8px; font-size: 13px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Adapterly Gateway</h1>
        <div class="subtitle">Setup Wizard</div>
    </div>
    <div class="steps">{steps_html}</div>
    <div class="container">
        {content}
    </div>
    <script>
    function testConnection(systemId, btn) {{
        btn.disabled = true;
        btn.textContent = 'Testing...';
        var resultEl = document.getElementById('test-result-' + systemId);
        resultEl.textContent = '';
        fetch('/setup/test/' + systemId, {{method: 'POST'}})
            .then(r => r.json())
            .then(data => {{
                resultEl.textContent = data.message;
                resultEl.className = 'test-result ' + (data.success ? 'success' : 'error');
                btn.disabled = false;
                btn.textContent = 'Test Connection';
                if (data.success) setTimeout(() => location.reload(), 1500);
            }})
            .catch(e => {{
                resultEl.textContent = 'Request failed: ' + e;
                resultEl.className = 'test-result error';
                btn.disabled = false;
                btn.textContent = 'Test Connection';
            }});
    }}
    function copyText(id) {{
        var el = document.getElementById(id);
        navigator.clipboard.writeText(el.textContent.trim());
        var btn = el.parentElement.querySelector('.copy-btn');
        if (btn) {{ btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 1500); }}
    }}
    </script>
</body>
</html>"""


def _render_step1(error: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return _setup_base_html(
        "Register",
        f"""
        <div class="card">
            <h2 style="margin-bottom:8px">Connect to Control Plane</h2>
            <p style="color:#666;margin-bottom:20px;font-size:14px">
                Enter your control plane URL and the one-time registration token
                from your Adapterly dashboard.
            </p>
            {error_html}
            <form method="post" action="/setup/register">
                <label>Control Plane URL</label>
                <input type="url" name="control_plane_url" value="https://adapterly.ai"
                       placeholder="https://adapterly.ai" required>

                <label>Registration Token</label>
                <input type="text" name="registration_token"
                       placeholder="gw_reg_..." required autofocus>

                <label>Gateway Name <span class="label-hint">(optional)</span></label>
                <input type="text" name="gateway_name"
                       placeholder="e.g. Production Gateway">

                <button type="submit" class="btn btn-primary" style="margin-top:8px">
                    Register Gateway
                </button>
            </form>
        </div>
    """,
        step=1,
    )


def _render_step2(systems: list, cred_map: dict) -> str:
    if not systems:
        rows_html = '<p style="color:#888">No systems synced yet. Please wait for sync to complete and refresh.</p>'
    else:
        rows_html = ""
        for system in systems:
            cred = cred_map.get(system.id)
            if cred and cred.is_verified:
                status_html = '<span class="status status-verified">Verified</span>'
                action_html = f'<a href="/setup/connect/{system.id}" class="btn btn-outline btn-sm">Edit</a>'
            elif cred:
                status_html = '<span class="status status-ok">Configured</span>'
                action_html = f'<a href="/setup/connect/{system.id}" class="btn btn-outline btn-sm">Edit</a>'
            else:
                status_html = '<span class="status status-none">Not connected</span>'
                action_html = f'<a href="/setup/connect/{system.id}" class="btn btn-primary btn-sm">Connect</a>'

            rows_html += f"""
            <div class="system-row">
                <div>
                    <strong>{escape(system.display_name)}</strong>
                    <span style="color:#888;font-size:13px">({escape(system.alias)})</span>
                    <br>{status_html}
                </div>
                <div>{action_html}</div>
            </div>"""

    return _setup_base_html(
        "Connect Integrations",
        f"""
        <div class="card">
            <h2 style="margin-bottom:8px">Configure Integrations</h2>
            <p style="color:#666;margin-bottom:20px;font-size:14px">
                Enter credentials for each system. Credentials are stored locally
                and never sent to the control plane.
            </p>
            {rows_html}
        </div>
        <div style="text-align:right;margin-top:16px">
            <a href="/setup/done" class="btn btn-success">Continue to Finish</a>
        </div>
    """,
        step=2,
    )


def _render_connect_form(system, fields, cred) -> str:

    fields_html = ""
    for field in fields:
        existing_val = ""
        placeholder = ""
        if cred:
            raw = getattr(cred, field.name, None)
            if field.sensitive and raw:
                placeholder = "***configured*** (leave empty to keep)"
            elif raw:
                existing_val = escape(str(raw))

        input_type = field.input_type
        required = "required" if field.required and not cred else ""

        fields_html += f"""
        <label>{escape(field.label)} {'<span class="label-hint">(optional)</span>' if not field.required else ""}</label>
        <input type="{input_type}" name="{escape(field.name)}"
               value="{existing_val}" placeholder="{placeholder}" {required}>
        """

    return _setup_base_html(
        f"Connect {system.display_name}",
        f"""
        <div class="card">
            <h2 style="margin-bottom:4px">Connect: {escape(system.display_name)}</h2>
            <p style="color:#888;font-size:13px;margin-bottom:20px">{escape(system.alias)} &middot; {escape(system.system_type)}</p>

            <form method="post" action="/setup/connect/{system.id}">
                {fields_html}
                <div class="flex" style="margin-top:8px">
                    <button type="submit" class="btn btn-primary">Save</button>
                    <button type="button" class="btn btn-outline"
                            onclick="testConnection({system.id}, this)">Test Connection</button>
                    <a href="/setup/integrations" class="btn" style="color:#888">Cancel</a>
                </div>
                <div id="test-result-{system.id}" class="test-result"></div>
            </form>
        </div>
    """,
        step=2,
    )


def _render_step3(host: str, scheme: str, api_key) -> str:
    base_url = f"{scheme}://{host}"
    mcp_url = f"{base_url}/mcp"

    key_display = f"{api_key.key_prefix}..." if api_key else "(no API key synced yet)"
    key_note = ""
    if not api_key:
        key_note = """
        <div class="error" style="margin-bottom:16px">
            No API key found. Create one in the Adapterly dashboard and wait for sync.
        </div>"""

    claude_config = (
        "{\n"
        '  "adapterly": {\n'
        f'    "url": "{mcp_url}",\n'
        '    "headers": {\n'
        f'      "Authorization": "Bearer {key_display}"\n'
        "    }\n"
        "  }\n"
        "}"
    )

    cursor_config = (
        "{\n"
        '  "mcpServers": {\n'
        '    "adapterly": {\n'
        f'      "url": "{mcp_url}",\n'
        '      "headers": {{\n'
        f'        "Authorization": "Bearer {key_display}"\n'
        "      }}\n"
        "    }\n"
        "  }\n"
        "}"
    )

    return _setup_base_html(
        "Setup Complete",
        f"""
        <div class="card">
            <h2 style="margin-bottom:12px;color:#28a745">Setup Complete!</h2>
            <p style="color:#666;margin-bottom:20px;font-size:14px">
                Your gateway is running and ready to serve MCP tools.
                Use the configurations below to connect your AI agent.
            </p>

            {key_note}

            <label>MCP Endpoint</label>
            <pre style="position:relative"><code id="endpoint">{escape(mcp_url)}</code><button class="copy-btn" onclick="copyText('endpoint')">Copy</button></pre>

            <label style="margin-top:16px">API Key</label>
            <pre style="position:relative"><code id="apikey">{escape(key_display)}</code><button class="copy-btn" onclick="copyText('apikey')">Copy</button></pre>
        </div>

        <div class="card">
            <h3 style="margin-bottom:12px">Claude Code / Claude Desktop</h3>
            <p style="color:#888;font-size:13px;margin-bottom:8px">Add to <code>mcp_servers</code> in settings:</p>
            <pre style="position:relative"><code id="claude-config">{escape(claude_config)}</code><button class="copy-btn" onclick="copyText('claude-config')">Copy</button></pre>
        </div>

        <div class="card">
            <h3 style="margin-bottom:12px">Cursor</h3>
            <p style="color:#888;font-size:13px;margin-bottom:8px">Add to <code>.cursor/mcp.json</code>:</p>
            <pre style="position:relative"><code id="cursor-config">{escape(cursor_config)}</code><button class="copy-btn" onclick="copyText('cursor-config')">Copy</button></pre>
        </div>

        <div style="text-align:center;margin-top:24px">
            <a href="/admin/" class="btn btn-primary">Go to Admin Dashboard</a>
        </div>
    """,
        step=3,
    )
