"""Premium Discord presentation helpers kept separate from academic rules."""

from __future__ import annotations

import discord


BRAND = 0x7C5CFC
SUCCESS = 0x2ED573
WARNING = 0xFFA502
ERROR = 0xFF4757
INFO = 0x38BDF8
MUTED = 0x747D8C

FULL_BLOCK = "▰"
EMPTY_BLOCK = "▱"

_TITLE_EMOJIS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("unavailable", "not saved", "not created", "not updated", "not completed", "not added", "not allowed", "invalid", "rejected", "cannot", "no profile"), "❌"),
    (("no ", "empty"), "📭"),
    (("warning", "review required", "overdue"), "⚠️"),
    (("saved", "created", "recorded", "completed", "updated", "imported", "connected"), "✅"),
    (("profile", "student"), "🎓"),
    (("study", "session", "pomodoro", "focus"), "⏱️"),
    (("plan", "today", "task"), "🗓️"),
    (("goal",), "🎯"),
    (("lecture", "youtube", "video"), "🎬"),
    (("syllabus", "curriculum"), "📚"),
    (("revision",), "🔁"),
    (("mistake",), "📕"),
    (("mock", "test"), "📝"),
    (("rank", "leaderboard"), "🏆"),
    (("discipline",), "🔥"),
    (("progress", "stats", "analytics", "coverage"), "📊"),
    (("voice", "speech"), "🎙️"),
    (("ai", "tutor", "academic manager"), "🧠"),
    (("news", "official", "notice"), "📢"),
    (("reminder",), "🔔"),
    (("privacy", "data", "delete", "export"), "🔒"),
    (("help", "getting started"), "🧭"),
)


def embed(title: str, description: str, *, color: int = BRAND) -> discord.Embed:
    """Create the consistent visual shell used by every NeetVerse command."""

    decorated = premium_title(title)
    value = discord.Embed(
        title=decorated[:256],
        description=str(description or "No information available.")[:4096],
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    value.set_author(name="NEETVERSE  •  ACADEMIC COMMAND CENTER")
    value.set_footer(text="NEETVERSE  •  FOCUS  →  TRACK  →  MASTER")
    return value


def premium_title(title: str) -> str:
    text = str(title or "NeetVerse").strip()
    first_codepoint = ord(text[0]) if text else 0
    if 0x2600 <= first_codepoint <= 0x27FF or first_codepoint >= 0x1F000:
        return text
    lowered = text.casefold()
    for needles, emoji in _TITLE_EMOJIS:
        if any(needle in lowered for needle in needles):
            return f"{emoji}  {text}"
    return f"✨  {text}"


def progress_bar(
    value: float | int,
    total: float | int = 100,
    *,
    width: int = 10,
    show_percent: bool = True,
) -> str:
    """Render a truthful clamped progress bar for mobile Discord panels."""

    maximum = float(total)
    current = float(value)
    ratio = 0.0 if maximum <= 0 else max(0.0, min(current / maximum, 1.0))
    cells = max(3, min(int(width), 16))
    filled = round(ratio * cells)
    visual = FULL_BLOCK * filled + EMPTY_BLOCK * (cells - filled)
    return f"`{visual}` **{ratio * 100:.0f}%**" if show_percent else f"`{visual}`"


def metric(label: str, value: str | int | float, emoji: str = "◆") -> str:
    return f"{emoji} **{label}**\n└ `{value}`"


def status_icon(status: str) -> str:
    state = str(status or "").strip().casefold().replace(" ", "_")
    return {
        "completed": "✅",
        "success": "✅",
        "active": "🟢",
        "running": "🟢",
        "in_progress": "🔵",
        "watching": "▶️",
        "planned": "🗓️",
        "pending": "⏳",
        "saved": "🔖",
        "scheduled": "🔁",
        "due": "🔔",
        "paused": "⏸️",
        "on_break": "☕",
        "resolved": "✅",
        "reopened": "♻️",
        "archived": "📦",
        "cancelled": "⛔",
        "failed": "❌",
        "review_required": "⚠️",
    }.get(state, "•")


def subject_icon(subject: str) -> str:
    lowered = str(subject or "").casefold()
    if "phys" in lowered:
        return "⚛️"
    if "chem" in lowered:
        return "🧪"
    if "bio" in lowered or "botany" in lowered or "zoology" in lowered:
        return "🧬"
    return "📖"


def compact_number(value: int | float) -> str:
    number = float(value)
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= divisor:
            formatted = number / divisor
            return f"{formatted:.1f}{suffix}".replace(".0", "")
    return f"{number:g}"


def sparkline(values: list[float | int]) -> str:
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    low, high = min(values), max(values)
    if high == low:
        return blocks[3] * len(values)
    return "".join(blocks[round((float(value) - low) / (high - low) * 7)] for value in values)


async def reply(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    value: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = True,
) -> None:
    if ephemeral and content and value is None and content[0].isascii():
        content = f"🔒 {content}"
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=value, view=view, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=value, view=view, ephemeral=ephemeral)


def duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
