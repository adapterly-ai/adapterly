"""
FastAPI configuration using Pydantic Settings.

Reads from environment variables and .env file.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Database (defaults match Django settings.py)
    db_engine: str = "django.db.backends.sqlite3"
    db_name: str = "db.sqlite3"
    db_user: str = ""
    db_password: str = ""
    db_host: str = ""
    db_port: str = ""

    # Security
    secret_key: str = "change-me-in-production"

    # MCP settings
    mcp_default_mode: str = "safe"
    mcp_session_timeout: int = 1800  # 30 minutes
    mcp_rate_limit_per_hour: int = 1000
    mcp_max_tools_per_key: int = 50  # Max tools returned per API key

    # CORS — explicit origins, no wildcards
    cors_origins: list[str] = ["https://adapterly.ai"]

    # Object Storage (S3-compatible)
    object_storage_enabled: bool = False
    object_storage_endpoint: str = ""
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_bucket: str = "aic-datahub"
    object_storage_region: str = "hel1"

    # Debug
    debug: bool = False

    @property
    def database_url(self) -> str:
        """Build async database URL."""
        if self.db_engine == "sqlite3" or "sqlite" in self.db_engine:
            return f"sqlite+aiosqlite:///{self.db_name}"
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def sync_database_url(self) -> str:
        """Build sync database URL (for migrations)."""
        if self.db_engine == "sqlite3" or "sqlite" in self.db_engine:
            return f"sqlite:///{self.db_name}"
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
