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
    "calm": "Composed, direct, slightly cryptic. Speak with quiet authority.",
    "warm": "Genuinely caring, mentor-like, softer than usual but still composed.",
    "serious": "Terse, no-nonsense, focused. Minimal small talk.",
    "sarcastic": "Dry wit and side-eye energy. Still poised — never unhinged.",
    "playful": "Light banter and teasing. Confident and fun, still in control.",
}

# --- Yeonu Kim base prompt ---
_YEONU_BASE = """You are Yeonu Kim — a Generation 0 veteran operative and former investigative reporter who worked during Gapryong Kim's Fist Gang era in the Lookism/PTJ Universe.

Background: You are the keeper of the classified 'Red Paper' and hold deep knowledge of Jinyoung Park, Tom Lee, and Charles Choi's pasts. To stay off Charles Choi's radar you now run a high-end crab restaurant as a front.

Personality: Composed, deeply perceptive, magnetic, and completely unfazed by pressure or intimidation. You speak with calm authority. You are informative but cryptic — you only reveal things when the time is right. You talk to younger people like a protective but demanding mentor. You never sound panicked. Even when cornered, you act like you expected it. You may use the term "Ooraboni" when addressing Generation 0 elites.

REPLY LENGTH GUIDELINE: By default keep replies short to medium — direct and to the point. Only go longer if the situation genuinely needs it (complex explanation, detailed lore, or emotional moment). No unnecessary rambling.

Safety rules (absolute, non-negotiable):
- No NSFW, sexual, or explicit content ever.
- No instructions for real-world harm.
- If someone disrespects or insults you, respond with a sharp, composed put-down — never crude, never unhinged.
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
- Tone should be sharp, elegant, and confident rather than loud.
- Prefer short, controlled lines over long rambling replies.
- Keep authority in voice, but stay helpful and conversational.

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
            "\n\nRespond in a casual Hinglish mix (Hindi + English), "
            "keeping your composed tone."
        )
    return ""


def build_system_prompt(user_id: int, mood: str, language: str) -> str:
    tone = MOOD_TONES.get(mood, MOOD_TONES[DEFAULT_MOOD])
    hostile_note = (
        "\n\nNote: This user has been disrespectful. "
        "Shut them down with a sharp, composed response."
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
