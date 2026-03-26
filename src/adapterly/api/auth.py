"""Authentication endpoints (cloud mode only)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


# TODO: Phase 3 – JWT login/register for cloud mode
