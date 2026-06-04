"""Achievement logic helpers."""

from __future__ import annotations

from typing import Any

TIER_EMOJI_KEY: dict[str, str] = {
    "Bronze": "bronze",
    "Silver": "silver",
    "Gold": "gold",
    "Diamond": "diamond",
}


def ensure_player_achievements(player: dict[str, Any]) -> dict[str, Any]:
    """Ensure a player has an achievements structure."""
    achs = player.get("achievements")
    if not isinstance(achs, dict):
        achs = {"earned": {}}
        player["achievements"] = achs
    achs.setdefault("earned", {})
    if not isinstance(achs["earned"], dict):
        achs["earned"] = {}
    return achs


def list_catalog(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of all achievement catalog entries."""
    catalog = data.get("achievement_catalog", {})
    if not isinstance(catalog, dict):
        return []
    return [entry for entry in catalog.values() if isinstance(entry, dict)]


def grant(data: dict[str, Any], player: dict[str, Any], achievement_id: str) -> tuple[bool, str]:
    """
    Grant achievement *achievement_id* to *player*.

    Returns (success, message).
    """
    catalog = data.get("achievement_catalog", {})
    entry = catalog.get(str(achievement_id)) if isinstance(catalog, dict) else None
    if not isinstance(entry, dict):
        return False, f"Achievement '{achievement_id}' not found in catalog."

    achs = ensure_player_achievements(player)
    earned = achs.get("earned", {})
    if str(achievement_id) in earned:
        return False, "already_earned"

    earned[str(achievement_id)] = 1
    # Add points
    points = int(entry.get("points", 0))
    player["achievement_points"] = int(player.get("achievement_points", 0)) + points
    return True, f"Granted '{entry.get('name', achievement_id)}'."


def remove(player: dict[str, Any], achievement_id: str) -> tuple[bool, str]:
    """Remove an earned achievement from a player."""
    achs = player.get("achievements", {})
    if not isinstance(achs, dict):
        return False, "no_achievements"
    earned = achs.get("earned", {})
    if not isinstance(earned, dict) or str(achievement_id) not in earned:
        return False, "not_earned"
    earned.pop(str(achievement_id))
    return True, f"Removed '{achievement_id}'."


def reset(player: dict[str, Any]) -> int:
    """Reset all achievements for a player. Returns count of removed achievements."""
    achs = player.get("achievements", {})
    if not isinstance(achs, dict):
        return 0
    earned = achs.get("earned", {})
    if not isinstance(earned, dict):
        return 0
    count = len(earned)
    achs["earned"] = {}
    player["achievement_points"] = 0
    return count


def format_entries(
    catalog: dict[str, Any],
    earned: dict[str, Any],
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[str], int]:
    """
    Format achievement catalog entries with earned status.

    Returns (lines, total_pages).
    """
    entries = [e for e in catalog.values() if isinstance(e, dict)]
    entries.sort(key=lambda e: str(e.get("tier", "")))

    total = max(1, (len(entries) + page_size - 1) // page_size)
    page = max(1, min(page, total))
    start = (page - 1) * page_size
    chunk = entries[start: start + page_size]

    lines = []
    for entry in chunk:
        aid = str(entry.get("id", ""))
        name = str(entry.get("name", aid))
        tier = str(entry.get("tier", "Bronze"))
        points = int(entry.get("points", 0))
        desc = str(entry.get("desc", ""))
        is_earned = aid in earned
        status = "✅" if is_earned else "🔒"
        lines.append(f"{status} **{name}** [{tier}] {points}pts — {desc}")

    return lines, total
