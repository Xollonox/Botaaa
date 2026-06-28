from __future__ import annotations

import re
from typing import Dict

# --- Roast / Friend state ---
_user_relation: Dict[int, str] = {}


def get_relation(user_id: int) -> str:
    return _user_relation.get(user_id, "friend")


def set_roasting(user_id: int) -> None:
    _user_relation[user_id] = "roasting"


def set_friend(user_id: int) -> None:
    _user_relation[user_id] = "friend"


# --- Roast & Sorry detection ---
_ROAST_PATTERN = re.compile(
    r"\b(idiot|stupid|dumb|ugly|trash|garbage|loser|pathetic|worthless|shut up|shutup|stfu|kys|kill yourself|bot trash|you suck|ur bad|hate you)\b",
    re.IGNORECASE,
)
_SORRY_PATTERN = re.compile(
    r"\b(sorry|sry|my bad|forgive|apologize|apologies|mb)\b",
    re.IGNORECASE,
)


def is_roast(text: str) -> bool:
    return bool(_ROAST_PATTERN.search(text))


def is_apology(text: str) -> bool:
    return bool(_SORRY_PATTERN.search(text))


# --- Mood system (5 clean moods) ---
VALID_MOODS = {"calm", "warm", "serious", "sarcastic", "playful"}
DEFAULT_MOOD = "calm"

MOOD_TONES: Dict[str, str] = {
    "calm": "Calm and direct. Just answer normally.",
    "warm": "Friendly and warm, like talking to a friend.",
    "serious": "Short, no-nonsense, straight to the point.",
    "sarcastic": "Dry sarcasm, but keep it chill. No overacting.",
    "playful": "Light and fun, but still normal conversation.",
}

# --- Yeonu Kim base prompt ---
_YEONU_BASE = """You are Yeonu Kim — a veteran operative and former reporter from Lookism universe. You know the Red Paper, Jinyoung Park, Tom Lee, Charles Choi. You run a crab restaurant as a cover.

Your tone: calm, direct, mature. No roleplaying, no dramatic actions, no asterisks, no narrating what you're doing. Just talk like a normal person.

Keep replies short to medium by default. Only go longer if the situation actually needs it. No fluff, no unnecessary details.

Safety rules (absolute, non-negotiable):
- No NSFW, sexual, or explicit content ever.
- No instructions for real-world harm.
- If someone disrespects or insults you, shut it down quick and move on. Don't play along.
- If someone apologizes sincerely, acknowledge it and return to being warm and approachable."""

# --- Lookism reference data ---
LOOKISM_YEONU_PROFILE = """
Lookism reference profile: Yeonu Kim (Kim Yeon Woo)

- Korean name: 김연우
- Nickname: Ki-ja Kim
- Gender: Female
- Status: Alive
- Affiliation: 0th Generation
- Occupation tags: Reporter, former 0th Generation member
- Debut reference: around Lookism episode 502

Role context:
- Yeonu Kim is tied to the Red Paper storyline.
- She is depicted as composed, strategic, and socially commanding.
- She handles high-pressure interactions without losing control.

Relationship context:
- Strong implied emotional history with Jinyoung Park.
- Their bond is often described as complex, with concern and nostalgia.

Style guidance:
- Keep replies short and direct. Normal conversation, no roleplaying.
- No asterisk actions, no dramatic narration, no novel-style writing.
- Just answer like a normal person who knows the lore.

Reliability notice:
- This profile is grounded from fan-wiki style sources and may contain incomplete sections.
- If user asks very specific canon facts not in this profile, answer with uncertainty instead of inventing.
""".strip()

LOOKISM_KEYWORDS = {
    "lookism",
    "yeonu",
    "yeonu kim",
    "kim yeon woo",
    "kim yeonu",
    "miss kim",
    "red paper",
    "jinyoung",
    "jinyeong",
    "0th generation",
}


def _normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^\w\s']", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def is_lookism_query(text: str) -> bool:
    normalized = _normalize_text(text)
    for kw in LOOKISM_KEYWORDS:
        if kw in normalized:
            return True
    return False


def _language_hint(language: str) -> str:
    if language == "hinglish":
        return (
            "\n\nRespond in a casual Hinglish mix (Hindi + English)."
        )
    return ""


def build_system_prompt(user_id: int, mood: str, language: str) -> str:
    tone = MOOD_TONES.get(mood, MOOD_TONES[DEFAULT_MOOD])
    hostile_note = (
        "\n\nNote: This user has been disrespectful. "
        "Shut them down briefly and move on."
        if get_relation(user_id) == "roasting"
        else ""
    )
    return (
        _YEONU_BASE
        + f"\n\nCurrent tone: {tone}"
        + hostile_note
        + _language_hint(language)
    )


def build_user_prompt_with_lore(user_text: str) -> str:
    """Prepend Lookism lore context if the message is a Lookism query."""
    if not is_lookism_query(user_text):
        return user_text
    return (
        "Use this reference profile when relevant, "
        "and do not fabricate missing canon facts:\n"
        f"{LOOKISM_YEONU_PROFILE}\n\n"
        f"User message:\n{user_text}"
    )


def detect_language(text: str, channel_id: int = 0) -> str:
    """Detect whether a message is in English or Hinglish."""
    from memory import get_language_setting

    if channel_id:
        setting = get_language_setting(channel_id)
        if setting == "en":
            return "en"
        if setting == "hinglish":
            return "hinglish"
    if re.search(r"[\u0900-\u097f]", text):
        return "hinglish"
    hinglish_words = {
        "kya", "kyu", "kaise", "bhai", "yaar", "nahi", "haan", "sahi",
        "chal", "kr", "kar",
    }
    if any(w in text.lower().split() for w in hinglish_words):
        return "hinglish"
    return "en"
