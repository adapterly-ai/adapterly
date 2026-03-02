"""
Local admin UI for the standalone gateway.

Provides a simple web interface for managing credentials.
Access restricted by admin password.
"""

import hashlib
import logging
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from gateway_core.crypto import encrypt_value
from gateway_core.models import AccountSystem, System

from ..config import get_settings
from ..database import get_db

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
        select(AccountSystem)
        .options(selectinload(AccountSystem.system))
        .where(AccountSystem.is_enabled == True)  # noqa: E712
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

    stmt = (
        select(AccountSystem)
        .where(AccountSystem.system_id == system_id)
        .where(AccountSystem.is_enabled == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    return HTMLResponse(_render_credential_form(system, cred))


@router.post("/credentials/{system_id}")
async def save_credential(
    request: Request,
    system_id: int,
    db: AsyncSession = Depends(get_db),
    username: str = Form(""),
    password: str = Form(""),
    api_key: str = Form(""),
    token: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
):
    _check_admin_auth(request)

    system = await db.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    stmt = (
        select(AccountSystem)
        .where(AccountSystem.system_id == system_id)
    )
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    if not cred:
        cred = AccountSystem(
            account_id=1,  # Standalone gateway uses account_id=1
            system_id=system_id,
            is_enabled=True,
        )
        db.add(cred)

    # Only update fields that were provided (non-empty)
    if username:
        cred.username = username
    if password:
        cred.password = encrypt_value(password)
    if api_key:
        cred.api_key = encrypt_value(api_key)
    if token:
        cred.token = encrypt_value(token)
    if client_id:
        cred.client_id = client_id
    if client_secret:
        cred.client_secret = encrypt_value(client_secret)

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
    return _base_html("Login", f"""
        <div class="card" style="max-width:400px;margin:100px auto">
            <h2>Gateway Admin</h2>
            {error_html}
            <form method="post" action="/admin/login">
                <label>Password</label>
                <input type="password" name="password" autofocus>
                <button type="submit" class="btn btn-primary">Login</button>
            </form>
        </div>
    """)


def _render_dashboard(systems: list, cred_map: dict) -> str:
    rows = ""
    for system in systems:
        cred = cred_map.get(system.id)
        if cred:
            status_html = '<span class="status status-ok">Configured</span>'
        else:
            status_html = '<span class="status status-none">No credentials</span>'

        rows += f"""
        <div class="card">
            <div class="flex">
                <div>
                    <strong>{system.display_name}</strong> ({system.alias})
                    <br>{status_html}
                </div>
                <a href="/admin/credentials/{system.id}" class="btn btn-primary btn-sm">Configure</a>
            </div>
        </div>
        """

    return _base_html("Dashboard", f"""
        <h1>Gateway Credentials</h1>
        <p style="margin-bottom:20px;color:#666">
            Credentials are stored locally on this gateway and never sent to the control plane.
        </p>
        {rows if rows else '<p>No systems synced yet. Check control plane connection.</p>'}
    """)


def _render_credential_form(system: Any, cred: AccountSystem | None) -> str:
    username = cred.username or "" if cred else ""
    pw_placeholder = "***configured***" if cred and cred.password else "Enter password"
    ak_placeholder = "***configured***" if cred and cred.api_key else "Enter API key"
    tok_placeholder = "***configured***" if cred and cred.token else "Enter token"
    cs_placeholder = "***configured***" if cred and cred.client_secret else "Enter client secret"
    client_id_val = cred.client_id or "" if cred else ""
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

    return _base_html(f"Configure {system.display_name}", f"""
        <h1>Configure: {system.display_name}</h1>
        <p style="margin-bottom:20px;color:#666">System: {system.alias} | Type: {system.system_type}</p>

        <div class="card">
            <form method="post" action="/admin/credentials/{system.id}">
                <label>Username</label>
                <input type="text" name="username" value="{username}" placeholder="Leave empty to keep current">

                <label>Password</label>
                <input type="password" name="password" placeholder="{pw_placeholder}">

                <label>API Key</label>
                <input type="password" name="api_key" placeholder="{ak_placeholder}">

                <label>Token</label>
                <input type="password" name="token" placeholder="{tok_placeholder}">

                <label>Client ID (OAuth)</label>
                <input type="text" name="client_id" value="{client_id_val}" placeholder="OAuth client ID">

                <label>Client Secret (OAuth)</label>
                <input type="password" name="client_secret" placeholder="{cs_placeholder}">

                <div style="margin-top:16px">
                    <button type="submit" class="btn btn-primary">Save Credentials</button>
                    <a href="/admin/" class="btn" style="color:#666">Cancel</a>
                </div>
            </form>
        </div>

        {delete_html}
    """)
