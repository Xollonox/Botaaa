import asyncio
import json
import logging
import os
from typing import Optional

from config import MEMORY_FILE, SETTINGS_FILE, SPECIAL_USER_ID

logger = logging.getLogger("misskim")

_memory_lock = asyncio.Lock()


def _load_json_file(path: str, default: dict) -> dict:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except Exception:
        logger.exception("Failed to load JSON file: %s", path)
        return default


def _save_json_file(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save JSON file: %s", path)


async def _save_json_file_async(path: str, data: dict) -> None:
    async with _memory_lock:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to save JSON file: %s", path)


BOT_MEMORY: dict = _load_json_file(MEMORY_FILE, {"users": {}, "channels": {}})
BOT_SETTINGS: dict = _load_json_file(
    SETTINGS_FILE,
    {"max_user_memory_items": 150, "max_channel_memory_items": 30, "summary_every": 10},
)


def _memory_limit(key: str, fallback: int) -> int:
    try:
        return max(1, int(BOT_SETTINGS.get(key, fallback)))
    except Exception:
        return fallback


def _memory_scope_key(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> str:
    user_prefix = "special" if user_id == SPECIAL_USER_ID else "user"
    return f"{user_prefix}:{user_id}"


def _scope_state(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> dict:
    users = BOT_MEMORY.setdefault("users", {})
    scope_key = _memory_scope_key(user_id, guild_id, channel_id)
    state = users.setdefault(scope_key, {})
    if isinstance(state, list):
        state = {"lines": state, "summary": "", "topic": "", "msg_count": 0}
        users[scope_key] = state
    state.setdefault("lines", [])
    state.setdefault("summary", "")
    state.setdefault("topic", "")
    state.setdefault("msg_count", 0)
    return state


def user_memory_text(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> str:
    state = _scope_state(user_id, guild_id, channel_id)
    lines = state.get("lines", [])
    if not lines:
        return ""
    trimmed = lines[-_memory_limit("max_user_memory_items", 80):]
    return "\n".join(trimmed)


async def remember_line(
    user_id: int,
    prefix: str,
    line: str,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    cleaned = line.strip()
    if prefix == "B" and cleaned.startswith(
        "I could not reach the AI backend right now"
    ):
        return
    state = _scope_state(user_id, guild_id, channel_id)
    lines = state["lines"]
    lines.append(f"{prefix}: {cleaned[:300]}")
    state["lines"] = lines[-_memory_limit("max_user_memory_items", 80):]
    state["msg_count"] = state.get("msg_count", 0) + 1
    topic = _detect_topic(lines[-10:])
    if topic:
        state["topic"] = topic
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)


def _detect_topic(lines: list) -> str:
    common_topics = {
        "lookism": [
            "lookism", "yeonu", "jinyoung", "red paper", "webtoon", "manhwa", "chapter",
        ],
        "game": [
            "game", "play", "gaming", "rpg", "mmo", "mobile legend", "valorant", "fortnite",
        ],
        "music": [
            "song", "music", "playlist", "album", "artist", "listen", "rap", "hip hop",
            "kpop", "rock",
        ],
        "movie": ["movie", "film", "show", "netflix", "anime", "series", "watch"],
        "food": ["food", "eat", "cook", "recipe", "hungry", "dinner", "lunch", "breakfast"],
        "tech": [
            "code", "coding", "programming", "python", "javascript", "ai", "bot", "api", "app",
        ],
        "life": ["work", "study", "school", "college", "job", "office", "exam", "test"],
        "sports": [
            "sport", "game", "match", "team", "win", "fight", "boxing", "mma",
            "basketball", "football",
        ],
        "relationship": [
            "love", "crush", "date", "girlfriend", "boyfriend", "relationship",
            "heart", "breakup",
        ],
    }
    text = " ".join(lines).lower()
    for topic, keywords in common_topics.items():
        for kw in keywords:
            if kw in text:
                return topic
    return ""


def add_memory_to_prompt(
    user_id: int,
    user_text: str,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> str:
    state = _scope_state(user_id, guild_id, channel_id)
    lines = state.get("lines", [])
    summary = state.get("summary", "")
    topic = state.get("topic", "")

    context_parts = []
    if summary:
        context_parts.append(f"[Conversation so far: {summary}]")
    if topic:
        context_parts.append(f"[Current topic: {topic}]")
    if lines:
        trimmed = get_relevant_memories(
            lines,
            user_text,
            max_items=30,
        )
        if trimmed:
            context_parts.append(
                "[Recent conversation:\n" + "\n".join(trimmed) + "]"
            )
    context_parts.append(f"[Now: {user_text}]")
    return "\n".join(context_parts)


def get_relevant_memories(
    all_memories: list,
    current_message: str,
    max_items: int = 30,
) -> list:
    if not all_memories:
        return []
    msg_words = set(current_message.lower().split())
    scored = []
    for mem in all_memories:
        mem_words = set(str(mem).lower().split())
        overlap = len(msg_words & mem_words)
        scored.append((overlap, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_items]]


async def update_conversation_summary(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    # Import here to avoid circular import at module load time
    from llm import chat_with_fallback

    state = _scope_state(user_id, guild_id, channel_id)
    lines = state.get("lines", [])
    if len(lines) < 4:
        return
    to_summarize = lines[:-4]
    if not to_summarize:
        return
    try:
        summary = await chat_with_fallback(
            system_prompt=(
                "Summarize this conversation in 1 short sentence. "
                "Focus on key topics, opinions, and ongoing context. "
                "Just the summary, no prefix."
            ),
            user_prompt="Conversation:\n" + "\n".join(to_summarize),
        )
        if "I could not reach the AI backend right now" not in summary:
            state["summary"] = summary.strip()[:300]
            state["lines"] = lines[-4:]
            _save_json_file(MEMORY_FILE, BOT_MEMORY)
    except Exception:
        logger.exception(
            "Conversation summary update failed | user=%s guild=%s channel=%s",
            user_id,
            guild_id,
            channel_id,
        )


def clear_user_memory(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    users = BOT_MEMORY.setdefault("users", {})
    users.pop(_memory_scope_key(user_id), None)
    _save_json_file(MEMORY_FILE, BOT_MEMORY)


def clear_all_memory() -> None:
    BOT_MEMORY["users"] = {}
    BOT_MEMORY["channels"] = {}
    _save_json_file(MEMORY_FILE, BOT_MEMORY)


def _should_summarize(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> bool:
    state = _scope_state(user_id, guild_id, channel_id)
    count = state.get("msg_count", 0)
    every = max(5, int(BOT_SETTINGS.get("summary_every", 10)))
    return count > 0 and count % every == 0


def get_language_setting(channel_id: int) -> str:
    channels = BOT_MEMORY.get("channels", {})
    return channels.get(str(channel_id), {}).get("lang", "auto")


def set_language_setting(channel_id: int, lang: str) -> None:
    channels = BOT_MEMORY.setdefault("channels", {})
    chan_data = channels.setdefault(str(channel_id), {})
    chan_data["lang"] = lang
    _save_json_file(MEMORY_FILE, BOT_MEMORY)


def get_mood(channel_id: int) -> str:
    channels = BOT_MEMORY.get("channels", {})
    return channels.get(str(channel_id), {}).get("mood", "calm")


def set_mood(channel_id: int, mood: str) -> None:
    channels = BOT_MEMORY.setdefault("channels", {})
    chan_data = channels.setdefault(str(channel_id), {})
    chan_data["mood"] = mood
    _save_json_file(MEMORY_FILE, BOT_MEMORY)
