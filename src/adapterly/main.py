"""FastAPI application factory."""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .crypto import configure_secret_key
from .database import close_engine


logger = logging.getLogger("adapterly")


async def _run_migrations():
    """Run Alembic migrations (create tables if needed)."""
    from .database import get_engine
    from .models import Base
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Configure crypto
    configure_secret_key(settings.SECRET_KEY)

    # Create tables
    await _run_migrations()

    # Standalone mode: auto-create account + API key
    if settings.is_standalone:
        from .setup.wizard import ensure_standalone_setup
        raw_key = await ensure_standalone_setup()
        if raw_key:
            logger.info(f"=== STANDALONE SETUP ===")
            logger.info(f"API Key (save this!): {raw_key}")
            logger.info(f"========================")

    # Load catalog integrations
    if settings.LOAD_CATALOG:
        from .catalog.loader import load_catalog
        await load_catalog()

    logger.info(f"Adapterly v2 started (mode={settings.MODE})")
    yield
    await close_engine()
    logger.info("Adapterly v2 shut down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Adapterly",
        version="2.0.0",
        description="Managed integrations for AI agents",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health endpoint
    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": settings.MODE, "version": "2.0.0"}

    # Mount routers
    from .mcp.router import router as mcp_router
    app.include_router(mcp_router)

    from .api.workspaces import router as ws_router
    from .api.integrations import router as int_router
    from .api.connections import router as conn_router
    from .api.api_keys import router as keys_router
    from .api.auth import router as auth_router
    app.include_router(auth_router)
    app.include_router(ws_router)
    app.include_router(int_router)
    app.include_router(conn_router)
    app.include_router(keys_router)

    return app


app = create_app()
