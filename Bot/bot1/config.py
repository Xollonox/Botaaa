import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


def _str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


DISCORD_TOKEN: str = _str("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in .env")

SPECIAL_USER_ID: int = _int("SPECIAL_USER_ID", 1152936208742240316)
CEREBRAS_API_KEY: str = _str("CEREBRAS_API_KEY")
CEREBRAS_API_KEY_2: str = _str("CEREBRAS_API_KEY_2")
CEREBRAS_BASE_URL: str = _str("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1")
CEREBRAS_MODEL: str = _str("CEREBRAS_MODEL", "llama3.1-8b")
GROQ_API_KEY: str = _str("GROQ_API_KEY")
GROQ_API_KEY_2: str = _str("GROQ_API_KEY_2")
GROQ_BASE_URL: str = _str("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL: str = _str("GROQ_MODEL", "llama-3.1-8b-instant")
SEARCH_MODEL: str = _str("SEARCH_MODEL", "groq/compound")
VISION_MODEL: str = _str("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OLLAMA_API_KEY: str = _str("OLLAMA_API_KEY")
OLLAMA_API_KEY_2: str = _str("OLLAMA_API_KEY_2")
OLLAMA_API_KEY_3: str = _str("OLLAMA_API_KEY_3")
OLLAMA_API_KEY_4: str = _str("OLLAMA_API_KEY_4")
OLLAMA_API_KEY_5: str = _str("OLLAMA_API_KEY_5")
OLLAMA_BASE_URL: str = _str("OLLAMA_BASE_URL", "https://ollama.com/api")
OLLAMA_MODEL: str = _str("OLLAMA_MODEL", "ministral-3:14b-cloud")
QWEN_FALLBACK_MODEL: str = _str("QWEN_FALLBACK_MODEL", "gpt-oss:20b-cloud")
CLOUDFLARE_ACCOUNT_ID: str = _str("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN: str = _str("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_FLUX_MODEL: str = _str("CLOUDFLARE_FLUX_MODEL", "@cf/black-forest-labs/flux-1-schnell")
CLOUDFLARE_FLUX2_DEV_IMG2IMG_MODEL: str = _str(
    "CLOUDFLARE_FLUX2_DEV_IMG2IMG_MODEL", "@cf/black-forest-labs/flux-2-dev"
)
CLOUDFLARE_SD15_IMG2IMG_MODEL: str = _str(
    "CLOUDFLARE_SD15_IMG2IMG_MODEL", "@cf/runwayml/stable-diffusion-v1-5-img2img"
)
BLUESMINDS_API_KEY: str = _str("BLUESMINDS_API_KEY")
BLUESMINDS_BASE_URL: str = _str("BLUESMINDS_BASE_URL", "https://api.bluesminds.com/v1")
BLUESMINDS_IMAGE_MODEL: str = _str("BLUESMINDS_IMAGE_MODEL", "grok-imagine-image-lite")
MEMORY_FILE: str = _str("MEMORY_FILE", "bot_memory.json")
SETTINGS_FILE: str = _str("SETTINGS_FILE", "bot_settings.json")
LOG_LEVEL: str = _str("LOG_LEVEL", "INFO")
