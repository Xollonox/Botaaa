"""Configuration for Lookism Bot v2."""

import os
from dotenv import load_dotenv

# Load Bot/bot2/.env explicitly so it works regardless of working directory
_bot2_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_bot2_dir, ".env"))

# BOT_TOKEN must be provided via environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN environment variable is not set. "
        "Please set it in your .env file or as an environment variable."
    )
OWNER_IDS = {1152936208742240316, 944972813041803285}
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "lookism_data.json")
SQLITE_PATH = os.getenv("LOOKISM_SQLITE_PATH", os.path.join(BASE_DIR, "lookism_data.sqlite3"))

# Set to a list of guild IDs for fast development sync, or None for global sync.
GUILD_IDS = None

OWNER_GUILD_ID = 1447875474364829748
