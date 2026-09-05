"""Configuration management and system paths for iina-mal-scrobbler."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

# Base directories
CONFIG_DIR = Path.home() / ".config" / "mal-scrobbler"
DATABASE_PATH = CONFIG_DIR / "mal-scrobbler.sqlite3"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "scrobbler.log"

# macOS Keychain identifiers
KEYCHAIN_SERVICE = "com.iina-mal-scrobbler"
KEYCHAIN_ACCOUNT_ACCESS = "access_token"
KEYCHAIN_ACCOUNT_REFRESH = "refresh_token"

# MyAnimeList OAuth & API Endpoints
# Note: MAL OAuth 2.0 PKCE requires code_challenge_method=plain
AUTH_URL = "https://myanimelist.net/v1/oauth2/authorize"
TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"
API_BASE_URL = "https://api.myanimelist.net/v2"

# Default OAuth Settings
DEFAULT_CALLBACK_HOST = "localhost"
DEFAULT_CALLBACK_PORT = 8484
DEFAULT_REDIRECT_URI = f"http://{DEFAULT_CALLBACK_HOST}:{DEFAULT_CALLBACK_PORT}/callback"

# Operational Thresholds
DEFAULT_SCROBBLE_THRESHOLD = 0.80  # 80% watched
MIN_MATCH_CONFIDENCE = 0.75       # Minimum score for auto-selection
AMBIGUITY_DELTA_THRESHOLD = 0.08  # If top 2 scores within this, flag ambiguous


def ensure_directories() -> None:
    """Ensure required configuration and logging directories exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    """Load configuration from JSON file or return defaults."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(config_data: dict[str, Any]) -> None:
    """Save configuration dictionary to JSON file."""
    ensure_directories()
    current = load_config()
    current.update(config_data)
    temp_file = CONFIG_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    temp_file.replace(CONFIG_FILE)


def get_client_id() -> Optional[str]:
    """Retrieve MAL Client ID from environment or configuration."""
    env_id = os.environ.get("MAL_CLIENT_ID")
    if env_id:
        return env_id.strip()

    cfg = load_config()
    cfg_id = cfg.get("client_id")
    if cfg_id and isinstance(cfg_id, str):
        return cfg_id.strip()

    return None


def set_client_id(client_id: str) -> None:
    """Save MAL Client ID into configuration."""
    save_config({"client_id": client_id.strip()})
