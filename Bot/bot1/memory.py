import asyncio
import json
import logging
import os
import tempfile
from typing import Optional

from config import MEMORY_FILE, SETTINGS_FILE, SPECIAL_USER_ID
from llm import LLM_ERROR_SENTINELS

logger = logging.getLogger("misskim")

_memory_lock = asyncio.Lock()

# ── Shared (channel-level) conversation memory ────────────────────────

async def remember_channel_line(
    channel_id: int,
    speaker_name: str,
    prefix: str,
    line: str,
    guild_id: Optional[int] = None,
) -> None:
    """
    Store a channel-wide message visible to ALL users in that channel.
    This lets User B see context from User A's conversation with the bot.
    """
    cleaned = line.strip()[:300]
    channels = BOT_MEMORY.setdefault("channels", {})
    chan_data = channels.setdefault(str(channel_id), {})
    chan_lines = chan_data.setdefault("conversation", [])
    chan_lines.append(f"{speaker_name} ({prefix}): {cleaned}")
    max_chan = _memory_limit("max_channel_memory_items", 30)
    chan_data["conversation"] = chan_lines[-max_chan:]
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)


def get_channel_context(channel_id: int) -> str:
    """Return recent channel conversation across all users."""
    channels = BOT_MEMORY.get("channels", {})
    chan_data = channels.get(str(channel_id), {})
    lines = chan_data.get("conversation", [])
    if not lines:
        return ""
    return "\n".join(lines)


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
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
        ) as f:
            tmp_name = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        logger.exception("Failed to save JSON file: %s", path)
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


async def _save_json_file_async(path: str, data: dict) -> None:
    async with _memory_lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save_json_file, path, data)


BOT_MEMORY: dict = _load_json_file(MEMORY_FILE, {"users": {}, "channels": {}})
BOT_SETTINGS: dict = _load_json_file(
    SETTINGS_FILE,
    {"max_user_memory_items": 150, "max_channel_memory_items": 80, "summary_every": 10},
)


def _memory_limit(key: str, fallback: int) -> int:
    try:
        return max(1, int(BOT_SETTINGS.get(key, fallback)))
    except Exception:
        return fallback


def _memory_scope_key(
    user_id: int,
    guild_id: Optional[int],
    channel_id: Optional[int] = None,
) -> str:
    user_prefix = "special" if (SPECIAL_USER_ID is not None and user_id == SPECIAL_USER_ID) else "user"
    if guild_id is None:
        return f"{user_prefix}:{user_id}:dm"
    if channel_id is not None:
        return f"{user_prefix}:{user_id}:guild:{guild_id}:chan:{channel_id}"
    return f"{user_prefix}:{user_id}:guild:{guild_id}"


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
    trimmed = lines[-_memory_limit("max_user_memory_items", 150):]
    return "\n".join(trimmed)


async def remember_line(
    user_id: int,
    prefix: str,
    line: str,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    cleaned = line.strip()
    if prefix == "B" and any(s in cleaned for s in LLM_ERROR_SENTINELS):
        return
    state = _scope_state(user_id, guild_id, channel_id)
    lines = state["lines"]
    lines.append(f"{prefix}: {cleaned[:300]}")
    state["lines"] = lines[-_memory_limit("max_user_memory_items", 150):]
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

    # Channel-level context — lets other users see what the channel conversation is about
    if guild_id is not None and channel_id is not None:
        channel_ctx = get_channel_context(channel_id)
        if channel_ctx:
            context_parts.append(
                "[Channel conversation (all users):\n" + channel_ctx + "]"
            )

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
        if not any(s in summary for s in LLM_ERROR_SENTINELS):
            state["summary"] = summary.strip()[:300]
            state["lines"] = lines[-4:]
            await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)
    except Exception:
        logger.exception(
            "Conversation summary update failed | user=%s guild=%s channel=%s",
            user_id,
            guild_id,
            channel_id,
        )


async def clear_user_memory(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    users = BOT_MEMORY.setdefault("users", {})
    users.pop(_memory_scope_key(user_id, guild_id, channel_id), None)
    if guild_id is None:
        users.pop(str(user_id), None)
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)


async def clear_all_memory() -> None:
    BOT_MEMORY["users"] = {}
    BOT_MEMORY["channels"] = {}
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)


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


async def set_language_setting(channel_id: int, lang: str) -> None:
    channels = BOT_MEMORY.setdefault("channels", {})
    chan_data = channels.setdefault(str(channel_id), {})
    chan_data["lang"] = lang
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)


def get_mood(channel_id: int) -> str:
    channels = BOT_MEMORY.get("channels", {})
    return channels.get(str(channel_id), {}).get("mood", "calm")


async def set_mood(channel_id: int, mood: str) -> None:
    channels = BOT_MEMORY.setdefault("channels", {})
    chan_data = channels.setdefault(str(channel_id), {})
    chan_data["mood"] = mood
    await _save_json_file_async(MEMORY_FILE, BOT_MEMORY)


def build_full_user_prompt(
    text: str,
    user_id: int,
    guild_id: Optional[int],
    channel_id: int,
) -> str:
    """Build the full user-facing prompt by injecting lore + memories.

    Kept in memory.py so both commands.py and events.py share one copy.
    Imports from persona are deferred to avoid the memory ↔ persona
    circular-import that would arise from a top-level import.
    """
    from persona import build_user_prompt_with_lore  # deferred — persona lazily imports memory

    lore_prompt = build_user_prompt_with_lore(text)
    return add_memory_to_prompt(
        user_id, lore_prompt, guild_id=guild_id, channel_id=channel_id
    )
