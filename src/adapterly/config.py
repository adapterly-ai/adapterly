"""Application configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Deployment mode
    MODE: str = "standalone"  # "standalone" | "cloud"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/adapterly.db"

    # Security
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24h

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    LOG_LEVEL: str = "info"

    # Catalog
    LOAD_CATALOG: bool = True

    # Stripe (cloud mode billing)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO_MONTHLY: str = ""
    STRIPE_PRICE_TEAM_MONTHLY: str = ""

    model_config = {"env_prefix": "ADAPTERLY_", "env_file": ".env", "extra": "ignore"}

    @property
    def is_standalone(self) -> bool:
        return self.MODE == "standalone"

    @property
    def is_cloud(self) -> bool:
        return self.MODE == "cloud"

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
