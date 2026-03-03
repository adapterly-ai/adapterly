"""
Gateway configuration — Pydantic settings.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


def _env_files() -> list[str]:
    """Return list of .env files to load (later files override earlier ones)."""
    files = [".env"]
    data_dir = os.environ.get("GATEWAY_DATA_DIR")
    if data_dir:
        files.append(os.path.join(data_dir, ".env"))
    db_path = os.environ.get("GATEWAY_DB_PATH")
    if db_path:
        db_dir = os.path.dirname(os.path.abspath(db_path))
        candidate = os.path.join(db_dir, ".env")
        if candidate not in files:
            files.append(candidate)
    return files


class GatewaySettings(BaseSettings):
    """Standalone gateway settings."""

    # Gateway identity
    gateway_id: str = ""
    gateway_secret: str = ""

    # Control plane
    control_plane_url: str = "https://adapterly.ai"

    # Local database
    db_path: str = "gateway.db"

    # Security
    secret_key: str = "change-me-in-production"
    admin_password: str = ""  # Required for local admin UI

    # Sync intervals (seconds)
    spec_sync_interval: int = 300  # 5 minutes
    key_sync_interval: int = 60  # 1 minute
    audit_push_interval: int = 30  # 30 seconds
    health_push_interval: int = 60  # 1 minute
    audit_push_batch_size: int = 100

    # MCP settings
    mcp_default_mode: str = "safe"
    mcp_session_timeout: int = 1800
    mcp_rate_limit_per_hour: int = 1000

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # CORS
    cors_origins: list[str] = []

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def is_registered(self) -> bool:
        return bool(self.gateway_id)

    class Config:
        env_file = _env_files()
        env_file_encoding = "utf-8"
        env_prefix = "GATEWAY_"
        extra = "ignore"


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()


def reload_settings() -> GatewaySettings:
    """Reload settings from .env (clears lru_cache). Used by setup wizard."""
    get_settings.cache_clear()
    return get_settings()
