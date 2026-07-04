"""Configuration for Lookism Bot v2."""

import os
import logging
from dotenv import load_dotenv

# Load Bot/bot2/.env explicitly so it works regardless of working directory
_bot2_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_bot2_dir, ".env"))

logger = logging.getLogger(__name__)

# BOT_TOKEN must be provided via environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")


def _parse_owner_ids(raw: str) -> set[int]:
    """Parse comma/semicolon-separated owner IDs from a string."""
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError:
            continue
    return ids


# Load OWNER_IDS from environment; empty set if unset
_owner_ids_raw = os.environ.get("LOOKISM_OWNER_IDS", "").strip()
OWNER_IDS = _parse_owner_ids(_owner_ids_raw) if _owner_ids_raw else set()
if not OWNER_IDS:
    logger.warning(
        "LOOKISM_OWNER_IDS environment variable is not set or empty. "
        "Owner commands will be disabled."
    )
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "lookism_data.json")
SQLITE_PATH = os.getenv("LOOKISM_SQLITE_PATH", os.path.join(BASE_DIR, "lookism_data.sqlite3"))

# Set to a list of guild IDs for fast development sync, or None for global sync.
GUILD_IDS = None

OWNER_GUILD_ID = 1447875474364829748


def assert_runtime_config() -> None:
    """Validate required runtime configuration.

    Called from the bot's main entry point (not at import time) to allow
    test collection and non-runtime imports to succeed even without .env.
    """
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN environment variable is not set. "
            "Please set it in your .env file or as an environment variable."
        )
