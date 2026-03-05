"""Configuration management for Adapterly CLI."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".adapterly"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """Load config from ~/.adapterly/config.json."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(config: dict):
    """Save config to ~/.adapterly/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def get_url() -> str | None:
    """Get API base URL from config or env."""
    import os

    return os.environ.get("ADAPTERLY_URL") or load_config().get("url")


def get_key() -> str | None:
    """Get API key from config or env."""
    import os

    return os.environ.get("ADAPTERLY_KEY") or load_config().get("key")
