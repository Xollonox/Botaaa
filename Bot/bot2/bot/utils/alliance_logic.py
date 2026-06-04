"""Alliance management helpers."""

from __future__ import annotations

from typing import Any


def find_alliance_by_name(data: dict[str, Any], name: str) -> tuple[str | None, dict[str, Any] | None]:
    """Find an alliance by name (case-insensitive). Returns (alliance_id, alliance_dict)."""
    alliances = data.get("alliances", {})
    if not isinstance(alliances, dict):
        return None, None
    name_lower = str(name).strip().lower()
    for aid, alliance in alliances.items():
        if isinstance(alliance, dict) and str(alliance.get("name", "")).lower() == name_lower:
            return str(aid), alliance
    return None, None


def get_gang_alliance_id(data: dict[str, Any], gang_id: str) -> str | None:
    """Return the alliance ID for a gang, or None."""
    gangs = data.get("gangs", {})
    gang = gangs.get(str(gang_id)) if isinstance(gangs, dict) else None
    if not isinstance(gang, dict):
        return None
    aid = gang.get("alliance_id")
    return str(aid) if aid else None


def compute_alliance_trophies(data: dict[str, Any], alliance: dict[str, Any]) -> int:
    """Compute total trophies for all members in an alliance."""
    gang_ids = alliance.get("gang_ids", alliance.get("gangs", []))
    if not isinstance(gang_ids, list):
        return 0
    gangs = data.get("gangs", {})
    players = data.get("players", {})
    total = 0
    for gid in gang_ids:
        gang = gangs.get(str(gid)) if isinstance(gangs, dict) else None
        if not isinstance(gang, dict):
            continue
        members = gang.get("members", [])
        if not isinstance(members, list):
            continue
        for uid in members:
            player = players.get(str(uid)) if isinstance(players, dict) else None
            if not isinstance(player, dict):
                continue
            user = player.get("user", {})
            if isinstance(user, dict):
                total += int(user.get("trophies", 0))
    return total


def apply_alliance_id_to_gang_members(
    data: dict[str, Any], gang_id: str, alliance_id: str | None
) -> None:
    """Set alliance_id on all player records belonging to *gang_id*."""
    gangs = data.get("gangs", {})
    gang = gangs.get(str(gang_id)) if isinstance(gangs, dict) else None
    if not isinstance(gang, dict):
        return
    members = gang.get("members", [])
    if not isinstance(members, list):
        return
    players = data.get("players", {})
    if not isinstance(players, dict):
        return
    for uid in members:
        player = players.get(str(uid))
        if isinstance(player, dict):
            player["alliance_id"] = alliance_id


def cooldown_remaining(last_ts: int, cooldown_seconds: int, now: int) -> int:
    """Return seconds remaining on a cooldown."""
    remaining = cooldown_seconds - (now - last_ts)
    return max(0, remaining)
