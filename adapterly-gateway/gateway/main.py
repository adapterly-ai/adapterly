"""
Adapterly Gateway — standalone MCP gateway.

Run with:
    uvicorn gateway.main:app --host 0.0.0.0 --port 8001
    # or
    python -m gateway.main
"""

import asyncio
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add parent directory to path so gateway_core is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from gateway_core.config import DeploymentMode
from gateway_core.crypto import configure_secret_key

from .config import get_settings

# Configure deployment mode
os.environ["DEPLOYMENT_MODE"] = "gateway"

settings = get_settings()

# Initialize crypto
configure_secret_key(settings.secret_key)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Adapterly Gateway",
    description="Standalone MCP gateway with local credential storage",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

# CORS
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Mcp-Session-Id"],
    )

# Include admin routes
from .admin.routes import router as admin_router
app.include_router(admin_router)


@app.on_event("startup")
async def startup():
    """Initialize database and start background sync tasks."""
    from .database import init_db

    logger.info("Initializing gateway database...")
    await init_db()
    logger.info("Database initialized")

    # Start background sync tasks
    if settings.gateway_secret:
        from .sync.spec_sync import spec_sync_loop
        from .sync.key_sync import key_sync_loop
        from .reporting.audit_reporter import audit_push_loop
        from .reporting.health_reporter import health_push_loop

        asyncio.create_task(spec_sync_loop())
        asyncio.create_task(key_sync_loop())
        asyncio.create_task(audit_push_loop())
        asyncio.create_task(health_push_loop())
        logger.info("Background sync tasks started")
    else:
        logger.warning(
            "No GATEWAY_GATEWAY_SECRET configured. "
            "Run 'adapterly-gateway register' to connect to a control plane."
        )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "adapterly-gateway",
        "version": "0.1.0",
        "gateway_id": settings.gateway_id or "not-registered",
        "mode": "gateway",
    }


# ---------------------------------------------------------------------------
# MCP endpoint (reuses gateway_core execution engine)
# ---------------------------------------------------------------------------

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_core.auth import validate_api_key
from gateway_core.executor import execute_system_tool, get_system_tools

from .database import get_db


@app.get("/mcp/v1/tools")
async def list_tools(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """List available MCP tools for the authenticated key."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")

    key = authorization[7:]
    try:
        api_key, project = await validate_api_key(key, db)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    project_id = project.id if project else None
    tools = await get_system_tools(db, api_key.account_id, project_id=project_id)

    return {
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["input_schema"],
            }
            for t in tools
        ]
    }


@app.post("/mcp/v1/call")
async def call_tool(
    request_body: dict,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Execute an MCP tool call."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")

    key = authorization[7:]
    try:
        api_key, project = await validate_api_key(key, db)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    tool_name = request_body.get("name")
    arguments = request_body.get("arguments", {})

    if not tool_name:
        raise HTTPException(status_code=400, detail="Missing tool name")

    project_id = project.id if project else None

    # Find the action_id for this tool
    tools = await get_system_tools(db, api_key.account_id, project_id=project_id)
    tool_def = next((t for t in tools if t["name"] == tool_name), None)

    if not tool_def:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    result = await execute_system_tool(
        db=db,
        action_id=tool_def["action_id"],
        account_id=api_key.account_id,
        params=arguments,
        project_id=project_id,
        store_datasets=False,  # No dataset store in standalone mode
    )

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "gateway.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
