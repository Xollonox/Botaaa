"""XP and Level system — permanent, never resets."""
from __future__ import annotations

import bisect
from typing import Any


# ── Precomputed XP thresholds (levels 1-100) ────────────────────────────────
_XP_THRESHOLDS: list[int] = []
_LEVELS_PRECOMPUTED = False


def _ensure_thresholds() -> None:
    global _XP_THRESHOLDS, _LEVELS_PRECOMPUTED
    if not _LEVELS_PRECOMPUTED:
        _XP_THRESHOLDS = [xp_for_level(lvl) for lvl in range(1, 101)]
        _LEVELS_PRECOMPUTED = True

def xp_for_level(level: int) -> int:
    """Total cumulative XP needed to reach this level."""
    if level <= 1:
        return 0
    total = 0
    for lvl in range(2, level + 1):
        total += int(500 * (1.2 ** (lvl - 2)))
    return total

def xp_to_next_level(level: int) -> int:
    """XP needed for just this one level step."""
    return int(500 * (1.2 ** (level - 1)))

def level_from_xp(xp: int) -> int:
    """Get current level from total XP using binary search."""
    _ensure_thresholds()
    idx = bisect.bisect_right(_XP_THRESHOLDS, int(xp))
    return max(1, min(100, idx))

def xp_progress(xp: int) -> tuple[int, int, int]:
    """Returns (level, xp_in_current_level, xp_needed_for_next)."""
    level     = level_from_xp(xp)
    base      = xp_for_level(level)
    next_base = xp_for_level(min(level + 1, 100))
    current   = xp - base
    needed    = max(1, next_base - base)
    return level, current, needed

def make_bar(current: int, total: int, slots: int = 10) -> str:
    pct    = max(0, min(1, current / max(1, total)))
    filled = round(pct * slots)
    return "█" * filled + "░" * (slots - filled)

XP_TABLE = {
    "ranked_win":     200, "ranked_loss":     75,
    "friendly_win":   100, "friendly_loss":   40,
    "tournament_win": 250, "tournament_loss": 100,
}

CP_TABLE = {
    "ranked_win":     50,  "ranked_loss":     20,
    "friendly_win":   25,  "friendly_loss":   10,
    "tournament_win": 75,  "tournament_loss": 30,
}

def grant_battle_xp_cp(data: dict[str, Any], user_id: str, battle_type: str) -> tuple[int, int]:
    """Grant XP + CP for a battle. Returns (xp_gained, cp_gained)."""
    xp_gain = XP_TABLE.get(battle_type, 0)
    cp_gain = CP_TABLE.get(battle_type, 0)
    player  = data.get("players", {}).get(str(user_id))
    if not isinstance(player, dict):
        return 0, 0
    user = player.get("user", {})
    if not isinstance(user, dict):
        return 0, 0

    # XP — permanent
    cur_xp       = int(user.get("xp", 0))
    user["xp"]   = cur_xp + xp_gain
    user["level"] = level_from_xp(user["xp"])

    # CP — seasonal
    season = data.get("season", {})
    if isinstance(season, dict) and season.get("active"):
        snum = str(season.get("current_season", 1))
        scp  = user.setdefault("season_cp", {})
        if not isinstance(scp, dict):
            user["season_cp"] = {}
            scp = user["season_cp"]
        scp[snum] = int(scp.get(snum, 0)) + cp_gain

    return xp_gain, cp_gain
