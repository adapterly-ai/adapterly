"""
Local admin UI for the standalone gateway.

Provides a simple web interface for managing credentials.
Access restricted by admin password.
"""

import logging
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from gateway_core.crypto import encrypt_value
from gateway_core.executor import _get_auth_headers
from gateway_core.models import AccountSystem, Interface, MCPApiKey, System

from ..config import get_settings
from ..database import get_db
from .credential_schema import get_credential_fields

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

# Simple session token store (in-memory, single process)
_admin_sessions: dict[str, float] = {}


def _check_admin_auth(request: Request):
    """Check if the request has a valid admin session."""
    token = request.cookies.get("gw_admin_token")
    if not token or token not in _admin_sessions:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return True


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return HTMLResponse(_render_login())


@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    settings = get_settings()
    if not settings.admin_password:
        raise HTTPException(status_code=500, detail="Admin password not configured")

    if password != settings.admin_password:
        return HTMLResponse(_render_login(error="Invalid password"), status_code=401)

    token = secrets.token_urlsafe(32)
    _admin_sessions[token] = datetime.utcnow().timestamp()

    response = RedirectResponse(url="/admin/", status_code=303)
    response.set_cookie("gw_admin_token", token, httponly=True, samesite="strict")
    return response


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("gw_admin_token")
    if token:
        _admin_sessions.pop(token, None)
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("gw_admin_token")
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    _check_admin_auth(request)

    # Get systems with credentials
    stmt = (
        select(System)
        .where(System.is_active == True)  # noqa: E712
        .order_by(System.display_name)
    )
    result = await db.execute(stmt)
    systems = result.scalars().all()

    # Get credentials
    cred_stmt = (
        select(AccountSystem).options(selectinload(AccountSystem.system)).where(AccountSystem.is_enabled == True)  # noqa: E712
    )
    cred_result = await db.execute(cred_stmt)
    credentials = cred_result.scalars().all()

    cred_map = {c.system_id: c for c in credentials}

    return HTMLResponse(_render_dashboard(systems, cred_map))


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------


@router.get("/credentials/{system_id}", response_class=HTMLResponse)
async def edit_credential(request: Request, system_id: int, db: AsyncSession = Depends(get_db)):
    _check_admin_auth(request)

    system = await db.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    fields = await get_credential_fields(system, db)

    stmt = (
        select(AccountSystem).where(AccountSystem.system_id == system_id).where(AccountSystem.is_enabled == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    return HTMLResponse(_render_credential_form(system, fields, cred))


@router.post("/credentials/{system_id}")
async def save_credential(
    request: Request,
    system_id: int,
    db: AsyncSession = Depends(get_db),
):
    _check_admin_auth(request)

    system = await db.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    form_data = await request.form()

    stmt = select(AccountSystem).where(AccountSystem.system_id == system_id)
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    if not cred:
        cred = AccountSystem(
            account_id=1,  # Standalone gateway uses account_id=1
            system_id=system_id,
            is_enabled=True,
        )
        db.add(cred)

    # Map form fields to AccountSystem columns
    sensitive_columns = {"password", "api_key", "token", "client_secret"}
    valid_columns = {"username", "password", "api_key", "token", "client_id", "client_secret"}

    for field_name in valid_columns:
        value = form_data.get(field_name, "")
        if value:
            if field_name in sensitive_columns:
                setattr(cred, field_name, encrypt_value(value))
            else:
                setattr(cred, field_name, value)

    cred.updated_at = datetime.utcnow()
    await db.commit()

    logger.info(f"Credentials updated for system {system.alias}")
    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/credentials/{system_id}/delete")
async def delete_credential(request: Request, system_id: int, db: AsyncSession = Depends(get_db)):
    _check_admin_auth(request)

    stmt = select(AccountSystem).where(AccountSystem.system_id == system_id)
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    if cred:
        await db.delete(cred)
        await db.commit()
        logger.info(f"Credentials deleted for system_id {system_id}")

    return RedirectResponse(url="/admin/", status_code=303)


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


@router.post("/credentials/{system_id}/test")
async def test_credential(request: Request, system_id: int, db: AsyncSession = Depends(get_db)):
    """Test connection for a system's credentials."""
    _check_admin_auth(request)

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
# Agent config
# ---------------------------------------------------------------------------


@router.get("/agent-config", response_class=HTMLResponse)
async def agent_config(request: Request, db: AsyncSession = Depends(get_db)):
    _check_admin_auth(request)

    settings = get_settings()
    host = request.headers.get("host", f"localhost:{settings.port}")
    scheme = request.url.scheme

    stmt = select(MCPApiKey).where(MCPApiKey.is_active == True).limit(1)  # noqa: E712
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    return HTMLResponse(_render_agent_config(host, scheme, api_key))


# ---------------------------------------------------------------------------
# HTML templates (inline, no Jinja2 dependency)
# ---------------------------------------------------------------------------


def _base_html(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>{title} — Adapterly Gateway</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f5f5f5; color: #333; line-height: 1.5; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #1a1a2e; margin-bottom: 20px; }}
        h2 {{ color: #16213e; margin-bottom: 15px; }}
        .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .btn {{ display: inline-block; padding: 8px 16px; border: none; border-radius: 4px;
               cursor: pointer; font-size: 14px; text-decoration: none; }}
        .btn-primary {{ background: #4361ee; color: white; }}
        .btn-danger {{ background: #e63946; color: white; }}
        .btn-sm {{ padding: 4px 12px; font-size: 12px; }}
        input[type=text], input[type=password] {{
            width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px;
            margin-bottom: 12px; font-size: 14px;
        }}
        label {{ display: block; font-weight: 600; margin-bottom: 4px; font-size: 14px; }}
        .status {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
        .status-ok {{ background: #d4edda; color: #155724; }}
        .status-none {{ background: #f8d7da; color: #721c24; }}
        .error {{ color: #e63946; margin-bottom: 12px; }}
        .nav {{ background: #1a1a2e; padding: 12px 20px; margin-bottom: 20px; }}
        .nav a {{ color: white; text-decoration: none; margin-right: 16px; }}
        .flex {{ display: flex; justify-content: space-between; align-items: center; }}
        form.inline {{ display: inline; }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="/admin/">Dashboard</a>
        <a href="/admin/agent-config">Agent Config</a>
        <form action="/admin/logout" method="post" class="inline" style="float:right">
            <button type="submit" class="btn btn-sm" style="background:transparent;color:#ccc;border:1px solid #555">Logout</button>
        </form>
    </div>
    <div class="container">
        {content}
    </div>
</body>
</html>"""


def _render_login(error: str = "") -> str:
    error_html = f'<p class="error">{error}</p>' if error else ""
    return _base_html(
        "Login",
        f"""
        <div class="card" style="max-width:400px;margin:100px auto">
            <h2>Gateway Admin</h2>
            {error_html}
            <form method="post" action="/admin/login">
                <label>Password</label>
                <input type="password" name="password" autofocus>
                <button type="submit" class="btn btn-primary">Login</button>
            </form>
        </div>
    """,
    )


def _render_dashboard(systems: list, cred_map: dict) -> str:
    rows = ""
    for system in systems:
        cred = cred_map.get(system.id)
        if cred and cred.is_verified:
            status_html = '<span class="status status-ok">Verified</span>'
        elif cred:
            status_html = '<span class="status status-ok">Configured</span>'
        else:
            status_html = '<span class="status status-none">No credentials</span>'

        rows += f"""
        <div class="card">
            <div class="flex">
                <div>
                    <strong>{escape(system.display_name)}</strong> ({escape(system.alias)})
                    <br>{status_html}
                </div>
                <a href="/admin/credentials/{system.id}" class="btn btn-primary btn-sm">Configure</a>
            </div>
        </div>
        """

    return _base_html(
        "Dashboard",
        f"""
        <h1>Gateway Credentials</h1>
        <p style="margin-bottom:20px;color:#666">
            Credentials are stored locally on this gateway and never sent to the control plane.
        </p>
        {rows if rows else "<p>No systems synced yet. Check control plane connection.</p>"}
    """,
    )


def _render_credential_form(system: Any, fields: list, cred: AccountSystem | None) -> str:
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
        opt_label = (
            "" if field.required else ' <span style="color:#888;font-weight:400;font-size:12px">(optional)</span>'
        )

        fields_html += f"""
                <label>{escape(field.label)}{opt_label}</label>
                <input type="{input_type}" name="{escape(field.name)}"
                       value="{existing_val}" placeholder="{placeholder}">
        """

    confirm_js = "return confirm('Delete credentials?')"
    delete_html = ""
    if cred:
        delete_html = (
            '<div class="card"><form method="post" action="/admin/credentials/'
            + str(system.id)
            + '/delete"><button type="submit" class="btn btn-danger btn-sm" onclick="'
            + confirm_js
            + '">Delete Credentials</button></form></div>'
        )

    test_btn = ""
    if cred:
        test_btn = f"""
            <button type="button" class="btn" style="background:#17a2b8;color:white"
                    onclick="testConnection({system.id}, this)">Test Connection</button>
            <span id="test-result-{system.id}" style="margin-left:8px;font-size:13px"></span>
        """

    return _base_html(
        f"Configure {escape(system.display_name)}",
        f"""
        <h1>Configure: {escape(system.display_name)}</h1>
        <p style="margin-bottom:20px;color:#666">System: {escape(system.alias)} | Type: {escape(system.system_type)}</p>

        <div class="card">
            <form method="post" action="/admin/credentials/{system.id}">
                {fields_html}
                <div style="margin-top:16px;display:flex;gap:8px;align-items:center">
                    <button type="submit" class="btn btn-primary">Save Credentials</button>
                    {test_btn}
                    <a href="/admin/" class="btn" style="color:#666">Cancel</a>
                </div>
            </form>
        </div>

        {delete_html}

        <script>
        function testConnection(systemId, btn) {{
            btn.disabled = true;
            btn.textContent = 'Testing...';
            var resultEl = document.getElementById('test-result-' + systemId);
            resultEl.textContent = '';
            fetch('/admin/credentials/' + systemId + '/test', {{method: 'POST'}})
                .then(r => r.json())
                .then(data => {{
                    resultEl.textContent = data.message;
                    resultEl.style.color = data.success ? '#28a745' : '#e63946';
                    btn.disabled = false;
                    btn.textContent = 'Test Connection';
                }})
                .catch(e => {{
                    resultEl.textContent = 'Request failed';
                    resultEl.style.color = '#e63946';
                    btn.disabled = false;
                    btn.textContent = 'Test Connection';
                }});
        }}
        </script>
    """,
    )


def _render_agent_config(host: str, scheme: str, api_key) -> str:
    base_url = f"{scheme}://{host}"
    mcp_url = f"{base_url}/mcp"

    key_display = f"{api_key.key_prefix}..." if api_key else "(no API key synced yet)"

    key_note = ""
    if not api_key:
        key_note = '<p style="color:#e63946;margin-bottom:16px">No API key found. Create one in the Adapterly dashboard and wait for sync.</p>'

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

    return _base_html(
        "Agent Config",
        f"""
        <h1>Agent Configuration</h1>
        <p style="margin-bottom:20px;color:#666">
            Use these settings to connect your AI agent to this gateway.
        </p>

        {key_note}

        <div class="card">
            <label>MCP Endpoint</label>
            <pre id="endpoint" style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:4px;cursor:pointer"
                 onclick="copyText('endpoint')">{escape(mcp_url)}</pre>
            <label style="margin-top:12px">API Key Prefix</label>
            <pre id="apikey" style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:4px;cursor:pointer"
                 onclick="copyText('apikey')">{escape(key_display)}</pre>
        </div>

        <div class="card">
            <h2>Claude Code / Claude Desktop</h2>
            <p style="color:#888;font-size:13px;margin-bottom:8px">Add to <code>mcp_servers</code> in settings:</p>
            <pre id="claude-cfg" style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:4px;cursor:pointer;overflow-x:auto"
                 onclick="copyText('claude-cfg')">{escape(claude_config)}</pre>
        </div>

        <div class="card">
            <h2>Cursor</h2>
            <p style="color:#888;font-size:13px;margin-bottom:8px">Add to <code>.cursor/mcp.json</code>:</p>
            <pre id="cursor-cfg" style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:4px;cursor:pointer;overflow-x:auto"
                 onclick="copyText('cursor-cfg')">{escape(cursor_config)}</pre>
        </div>

        <script>
        function copyText(id) {{
            navigator.clipboard.writeText(document.getElementById(id).textContent.trim());
        }}
        </script>
    """,
    )
