"""
FastAPI application entry point.

Run with:
    uvicorn fastapi_app.main:app --reload --port 8001
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .mcp.router import router as mcp_router

settings = get_settings()

# Initialize gateway_core crypto with the secret key (must happen before any decrypt calls)
from gateway_core.crypto import configure_secret_key

configure_secret_key(settings.secret_key)

app = FastAPI(
    title="Adapterly API",
    description="MCP and REST API for Adapterly",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Mcp-Session-Id"],
)

# Include routers
app.include_router(mcp_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "fastapi"}
