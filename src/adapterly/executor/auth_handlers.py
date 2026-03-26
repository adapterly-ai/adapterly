"""Auth token refresh handlers (OAuth2, DRF token, etc.)."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt

from ..crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)


def detect_token_expiry(token: str, default_ttl: int = 86400) -> int:
    """Detect token expiry from JWT exp claim."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp:
            remaining = int(exp) - int(time.time()) - 300
            return max(remaining, 0)
    except Exception:
        pass
    return default_ttl
