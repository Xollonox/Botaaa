"""Profile embed builders (PIL-free replacement for profile_render.py).

Produces a boxy ANSI-colored 2×2 grid + full-width STATUS box, matching the
Terms / About / Account onboarding aesthetic. Discord renders ANSI escape
sequences inside ```ansi``` code blocks (red border, gold values, cyan
section headers, green featured card name).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import discord

from bot.utils.ui import e, make_embed
from bot.utils.xp_logic import xp_progress

_MAX_BIO_LENGTH = 150
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MENTION_RE = re.compile(r"@(?:everyone|here)", re.IGNORECASE)

_RARITY_ORDER = {
    "mythical": 6, "legendary": 5, "epic": 4,
    "rare": 3, "common": 2, "basic": 1,
}

# ── ANSI palette (Discord ```ansi``` code blocks) ─────────────────────────
_R = "\u001b[0m"           # reset
_RED = "\u001b[1;31m"      # bold red — outer border
_GOLD = "\u001b[1;33m"     # bold gold — title + numeric values
_CYAN = "\u001b[1;36m"     # bold cyan — section headers
_GREEN = "\u001b[0;32m"    # green — featured card
_YELLOW = "\u001b[0;33m"   # yellow — status quote

_SIDE_INNER = 15                # inner width per side box
_SIDE_OUTER = _SIDE_INNER + 2   # 17
_TOTAL_WIDTH = _SIDE_OUTER * 2 + 1   # 35 — same as the About embed, mobile-safe
_FULL_INNER = _TOTAL_WIDTH - 2  # 33


# ── Data helpers (PIL-free) ────────────────────────────────────────────────

def _sanitize_bio(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text or "")
    text = _MENTION_RE.sub("", text)
    return text.strip()


def _display_name(target: discord.abc.User) -> str:
    return (
        getattr(target, "display_name", None)
        or getattr(target, "global_name", None)
        or target.name
    )


def _join_date(user_data: dict[str, Any]) -> str:
    ts = int(user_data.get("registered_at", 0) or 0)
    if ts <= 0:
        return "Unknown"
    return datetime.utcfromtimestamp(ts).strftime("%d %b")


def _gang_name(data: dict[str, Any], player: dict[str, Any]) -> str:
    gang_id = player.get("gang_id") if isinstance(player, dict) else None
    gangs = data.get("gangs", {})
    if gang_id and isinstance(gangs, dict):
        gang = gangs.get(str(gang_id), {})
        if isinstance(gang, dict):
            return str(gang.get("name", gang_id))
    return "None"


def _war_points(player: dict[str, Any], user_data: dict[str, Any]) -> int:
    for src in (user_data, player if isinstance(player, dict) else {}):
        for key in ("war_points", "warpoints", "war_pts"):
            val = src.get(key)
            if val is not None:
                return int(val)
    return 0


def _achievements_count(user_data: dict[str, Any]) -> int:
    a = user_data.get("achievements", [])
    if isinstance(a, (list, dict)):
        return len(a)
    return int(user_data.get("achievements_count", 0) or 0)


def _cards_unlocked_count(user_data: dict[str, Any]) -> int:
    inv = user_data.get("inventory", [])
    if isinstance(inv, list):
        return len(inv)
    return int(user_data.get("cards_unlocked", 0) or 0)


def _badges_count(user_data: dict[str, Any]) -> int:
    badges = user_data.get("badges", [])
    if isinstance(badges, (list, dict)):
        return len(badges)
    return 0


def _rank_rows(data: dict[str, Any]) -> list[tuple[str, int]]:
    players = data.get("players", {})
    if not isinstance(players, dict):
        return []
    rows: list[tuple[str, int]] = []
    for uid, player in players.items():
        if not isinstance(player, dict):
            continue
        user = player.get("user", {})
        if not isinstance(user, dict):
            continue
        rows.append((str(uid), int(user.get("trophies", 0))))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def _global_rank(data: dict[str, Any], target_id: str) -> int:
    for i, (uid, _) in enumerate(_rank_rows(data), 1):
        if uid == target_id:
            return i
    return 0


def _xp_pct(user_data: dict[str, Any]) -> int:
    raw_xp = int(user_data.get("xp", 0) or 0)
    _level, cur, needed = xp_progress(raw_xp)
    if needed <= 0:
        return 0
    return int(max(0.0, min(1.0, cur / needed)) * 100)


def _resolve_card_by_uid(inventory: list[dict[str, Any]], uid: str) -> dict[str, Any] | None:
    return next(
        (i for i in inventory if isinstance(i, dict) and str(i.get("uid", "")) == uid),
        None,
    )


def _resolve_card_catalog_entry(cards_catalog: dict[str, Any], card_name: str) -> dict[str, Any]:
    if not isinstance(cards_catalog, dict):
        return {}
    normalized = str(card_name or "").strip()
    if not normalized:
        return {}
    direct = cards_catalog.get(normalized)
    if isinstance(direct, dict):
        return direct
    lowered = normalized.casefold()
    for key, value in cards_catalog.items():
        if not isinstance(value, dict):
            continue
        names = {
            str(key).strip(),
            str(value.get("name", "")).strip(),
            str(value.get("card_name", "")).strip(),
        }
        if any(n and n.casefold() == lowered for n in names):
            return value
    return {}


def _card_image_value(card: dict[str, Any] | None) -> str:
    if not isinstance(card, dict):
        return ""
    for key in ("image_url", "image", "img_url", "img", "card_image", "art_url", "thumbnail_url"):
        v = str(card.get(key) or "").strip()
        if v.startswith(("http://", "https://")):
            return v
    art = card.get("art", {})
    if isinstance(art, dict):
        for key in ("image_url", "image", "url", "thumbnail_url"):
            v = str(art.get(key) or "").strip()
            if v.startswith(("http://", "https://")):
                return v
    return ""


def _featured_card_block(data: dict[str, Any], user_data: dict[str, Any]) -> tuple[str, str]:
    profile_data = user_data.get("profile", {}) if isinstance(user_data.get("profile"), dict) else {}
    featured_uid = str(profile_data.get("showcase_uid", "")).strip()
    inventory = user_data.get("inventory", []) if isinstance(user_data.get("inventory"), list) else []
    cards_catalog = data.get("cards", {}) if isinstance(data.get("cards"), dict) else {}
    if not featured_uid:
        return "No featured card", ""
    card = _resolve_card_by_uid(inventory, featured_uid)
    if not isinstance(card, dict):
        return "No featured card", ""
    card_name = str(card.get("card_name") or card.get("name") or "Unknown").strip() or "Unknown"
    card_def = _resolve_card_catalog_entry(cards_catalog, card_name)
    image_url = _card_image_value(card) or _card_image_value(card_def)
    return card_name, image_url


# ── Box rendering (2-column, 35 chars total wide) ─────────────────────────

def _center_in(text: str, inner: int) -> tuple[int, int]:
    if len(text) >= inner:
        return 0, 0
    total_pad = inner - len(text)
    left = total_pad // 2
    return left, total_pad - left


def _title_box(title: str) -> list[str]:
    text = title if len(title) <= _FULL_INNER else title[: _FULL_INNER - 1] + "…"
    left, right = _center_in(text, _FULL_INNER)
    return [
        f"{_RED}╔{'═' * _FULL_INNER}╗{_R}",
        f"{_RED}║{_R}{' ' * left}{_GOLD}{text}{_R}{' ' * right}{_RED}║{_R}",
        f"{_RED}╚{'═' * _FULL_INNER}╝{_R}",
    ]


def _side_stat(label: str, value: str, *, color: str = _GOLD) -> str:
    """`│ Label     Value │` — inner width 15."""
    plain_len = 1 + len(label) + len(value) + 1
    pad = _SIDE_INNER - plain_len
    if pad < 1:
        value = value[: max(0, _SIDE_INNER - 1 - len(label) - 1 - 1)] + "…"
        pad = _SIDE_INNER - (1 + len(label) + len(value) + 1)
    return f"│ {label}{' ' * pad}{color}{value}{_R} │"


def _side_top(name: str) -> str:
    label = f" {name} "
    remaining = _SIDE_INNER - 3 - len(label)
    if remaining < 0:
        # Truncate name so it always fits.
        label = f" {name[: _SIDE_INNER - 4]} "
        remaining = _SIDE_INNER - 3 - len(label)
    return f"╭{'─' * 3}{_CYAN}{label}{_R}{'─' * remaining}╮"


def _side_bottom() -> str:
    return f"╰{'─' * _SIDE_INNER}╯"


def _side_blank() -> str:
    return f"│{' ' * _SIDE_INNER}│"


def _pair(left: str, right: str) -> str:
    return f"{left} {right}"


def _full_top(name: str) -> str:
    label = f" {name} "
    remaining = _FULL_INNER - 3 - len(label)
    if remaining < 0:
        remaining = 0
    return f"╭{'─' * 3}{_CYAN}{label}{_R}{'─' * remaining}╮"


def _full_bottom() -> str:
    return f"╰{'─' * _FULL_INNER}╯"


def _full_blank() -> str:
    return f"│{' ' * _FULL_INNER}│"


def _full_text_rows(text: str, *, color: str = "") -> list[str]:
    """Wrap *text* across rows inside the full-width (35-char) box."""
    available = _FULL_INNER - 4  # 2 leading + 2 trailing spaces
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = f"{cur} {w}".strip()
        if len(candidate) <= available:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            while len(w) > available:
                lines.append(w[:available])
                w = w[available:]
            cur = w
    if cur:
        lines.append(cur)
    if not lines:
        lines = [text[:available]]
    return [
        f"│  {color}{ln}{_R if color else ''}{' ' * (_FULL_INNER - 4 - len(ln))}  │"
        for ln in lines
    ]


# ── Main builder ──────────────────────────────────────────────────────────

def build_profile_embed(data: dict[str, Any], target: discord.abc.User) -> discord.Embed:
    target_id = str(target.id)
    players = data.get("players", {}) if isinstance(data.get("players"), dict) else {}
    player = players.get(target_id, {}) if isinstance(players, dict) else {}
    user_data = player.get("user", {}) if isinstance(player, dict) else {}
    if not isinstance(user_data, dict):
        user_data = {}
    profile_data = user_data.get("profile", {}) if isinstance(user_data.get("profile"), dict) else {}
    ranked = player.get("ranked_stats", {}) if isinstance(player, dict) else {}
    if not isinstance(ranked, dict):
        ranked = {}

    display_name = _display_name(target)
    league = str(user_data.get("rank", "Copper") or "Copper")
    global_rank = _global_rank(data, target_id)
    trophies = int(user_data.get("trophies", 0) or 0)
    xp_pct = _xp_pct(user_data)

    wins = int(ranked.get("wins", 0))
    losses = int(ranked.get("losses", 0))
    streak = int(ranked.get("streak", 0))
    battles = wins + losses
    win_rate = f"{(wins / battles * 100):.1f}%" if battles else "0.0%"

    cards = _cards_unlocked_count(user_data)
    achievements = _achievements_count(user_data)
    badges = _badges_count(user_data)
    war_pts = _war_points(player, user_data)

    status_raw = _sanitize_bio(str(profile_data.get("bio", "") or ""))
    status_line = f'"{status_raw}"' if status_raw else "No status set."

    global_display = f"#{global_rank}" if global_rank else "—"
    gang = _gang_name(data, player)
    joined = _join_date(user_data)

    lines: list[str] = ["```ansi", *_title_box(f"PROFILE · {display_name}")]

    def pair_row(name_l: str, rows_l: list[tuple[str, str]],
                 name_r: str, rows_r: list[tuple[str, str]]) -> None:
        # Pad the shorter side with blank rows so both boxes end evenly.
        depth = max(len(rows_l), len(rows_r))
        lines.append(_pair(_side_top(name_l), _side_top(name_r)))
        lines.append(_pair(_side_blank(), _side_blank()))
        for i in range(depth):
            l = _side_stat(*rows_l[i]) if i < len(rows_l) else _side_blank()
            r = _side_stat(*rows_r[i]) if i < len(rows_r) else _side_blank()
            lines.append(_pair(l, r))
        lines.append(_pair(_side_blank(), _side_blank()))
        lines.append(_pair(_side_bottom(), _side_bottom()))

    pair_row(
        "LEAGUE", [
            ("Rank", league),
            ("Global", global_display),
            ("Trophy", f"{trophies:,}"),
            ("XP", f"{xp_pct}%"),
        ],
        "BATTLE", [
            ("Wins", str(wins)),
            ("Losses", str(losses)),
            ("Rate", win_rate),
            ("Streak", str(streak)),
        ],
    )
    pair_row(
        "CARDS", [
            ("Cards", str(cards)),
            ("Achv.", str(achievements)),
            ("Badges", str(badges)),
        ],
        "GANG", [
            ("Name", gang),
            ("War", str(war_pts)),
            ("Since", joined),
        ],
    )

    # STATUS — full-width, wraps across multiple lines if the message is long.
    lines.append(_full_top("STATUS"))
    lines.append(_full_blank())
    lines.extend(_full_text_rows(status_line, color=_YELLOW if status_raw else ""))
    lines.append(_full_blank())
    lines.append(_full_bottom())
    lines.append("```")

    embed = discord.Embed(
        color=0x2B2D31,
        description="\n".join(lines),
    )
    avatar_url = getattr(getattr(target, "display_avatar", None), "url", None)
    # Avatar in the top-left circle, next to the author name.
    embed.set_author(name=f"LOOKISM CG · {display_name}", icon_url=avatar_url)
    embed.set_footer(text="Player Profile")
    return embed


def build_featured_card_embed(data: dict[str, Any], target: discord.abc.User) -> discord.Embed:
    target_id = str(target.id)
    players = data.get("players", {})
    player = players.get(target_id, {}) if isinstance(players, dict) else {}
    user_data = player.get("user", {}) if isinstance(player, dict) else {}
    if not isinstance(user_data, dict):
        user_data = {}
    featured_name, featured_image_url = _featured_card_block(data, user_data)
    if featured_image_url.startswith(("http://", "https://")):
        return make_embed(
            None,
            featured_name or "No featured card",
            "",
            footer="Featured Card",
            image_url=featured_image_url,
        )
    return make_embed(
        None,
        featured_name or "No featured card",
        "No featured card selected.",
        footer="Featured Card",
    )
