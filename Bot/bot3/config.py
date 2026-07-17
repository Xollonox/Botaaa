"""Environment-backed configuration for NeetVerse."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DISCORD_TOKEN = os.getenv("NEETVERSE_TOKEN", "").strip()
DATABASE_PATH = Path(os.getenv("NEETVERSE_DATABASE_PATH", str(BASE_DIR / "neetverse.sqlite3")))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"
OPENROUTER_TIMEOUT_SECONDS = max(10, int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60")))
AI_DAILY_GLOBAL_LIMIT = max(1, int(os.getenv("NEETVERSE_AI_DAILY_GLOBAL_LIMIT", "45")))
AI_DAILY_USER_LIMIT = max(1, int(os.getenv("NEETVERSE_AI_DAILY_USER_LIMIT", "10")))
TTS_DEFAULT_VOICE = os.getenv("NEETVERSE_TTS_DEFAULT_VOICE", "en-IN-NeerjaNeural").strip() or "en-IN-NeerjaNeural"
TTS_TIMEOUT_SECONDS = max(10, int(os.getenv("NEETVERSE_TTS_TIMEOUT_SECONDS", "45")))
TTS_MAX_CHARACTERS = max(200, min(int(os.getenv("NEETVERSE_TTS_MAX_CHARACTERS", "1800")), 4000))
VOICE_QUEUE_LIMIT = max(1, min(int(os.getenv("NEETVERSE_VOICE_QUEUE_LIMIT", "5")), 20))
VOICE_IDLE_SECONDS = max(30, int(os.getenv("NEETVERSE_VOICE_IDLE_SECONDS", "300")))
SEARCH_COOLDOWN_SECONDS = max(5, int(os.getenv("NEETVERSE_SEARCH_COOLDOWN_SECONDS", "20")))
SEARCH_USER_DAILY_LIMIT = max(1, int(os.getenv("NEETVERSE_SEARCH_USER_DAILY_LIMIT", "10")))
SEARCH_GLOBAL_DAILY_LIMIT = max(1, int(os.getenv("NEETVERSE_SEARCH_GLOBAL_DAILY_LIMIT", "100")))
LOG_LEVEL = os.getenv("NEETVERSE_LOG_LEVEL", "INFO").upper()
GUILD_IDS = tuple(
    int(part.strip())
    for part in os.getenv("NEETVERSE_GUILD_IDS", "").split(",")
    if part.strip().isdigit()
)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_API_BASE_URL = os.getenv("YOUTUBE_API_BASE_URL", "https://www.googleapis.com/youtube/v3").rstrip("/")
OWNER_IDS = frozenset(
    int(part.strip())
    for part in os.getenv("NEETVERSE_OWNER_IDS", "").split(",")
    if part.strip().isdigit()
)


def require_runtime_config() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("NEETVERSE_TOKEN is required")
