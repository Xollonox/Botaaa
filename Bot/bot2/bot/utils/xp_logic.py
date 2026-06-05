"""XP and Level system — permanent, never resets."""
from __future__ import annotations

import bisect
from typing import Any


# ── Milestone rewards given when player reaches these levels ────────────────
LEVEL_MILESTONES: dict[int, dict] = {
    5:   {"coins": 500,   "message": "🎉 Level 5! Keep climbing!"},
    10:  {"coins": 1000,  "pack": "amateur_pack",   "message": "🏆 Level 10! Amateur Pack unlocked!"},
    15:  {"coins": 1500,  "message": "⚡ Level 15! You're getting stronger!"},
    20:  {"coins": 2000,  "pack": "basic_pack",     "gems": 10, "message": "💎 Level 20! Basic Pack + 10 Gems!"},
    25:  {"coins": 3000,  "message": "🔥 Level 25! A quarter of the way there!"},
    30:  {"coins": 4000,  "pack": "intermediate_pack", "message": "⭐ Level 30! Intermediate Pack unlocked!"},
    40:  {"coins": 5000,  "gems": 15, "message": "🌟 Level 40! 15 Gems reward!"},
    50:  {"coins": 8000,  "pack": "experienced_pack", "gems": 25, "message": "👑 Level 50! Experienced Pack + 25 Gems! Halfway there!"},
    75:  {"coins": 12000, "pack": "veteran_pack",   "gems": 50, "message": "💫 Level 75! Veteran Pack + 50 Gems!"},
    100: {"coins": 20000, "gems": 100, "message": "🏆 MAX LEVEL 100! Legendary achievement! 20,000 coins + 100 Gems!"},
}


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

def grant_battle_xp_cp(data: dict[str, Any], user_id: str, battle_type: str) -> tuple[int, int, list[dict]]:
    """
    Grant XP + CP for a battle.
    Returns (xp_gained, cp_gained, milestone_rewards_list).

    milestone_rewards_list contains dicts with keys: level, coins, gems, pack, message.
    """
    xp_gain = XP_TABLE.get(battle_type, 0)
    cp_gain = CP_TABLE.get(battle_type, 0)
    player  = data.get("players", {}).get(str(user_id))
    if not isinstance(player, dict):
        return 0, 0, []
    user = player.get("user", {})
    if not isinstance(user, dict):
        return 0, 0, []

    # Track old level before XP is applied
    old_level = level_from_xp(int(user.get("xp", 0)))

    # XP — permanent
    cur_xp       = int(user.get("xp", 0))
    user["xp"]   = cur_xp + xp_gain
    new_level    = level_from_xp(user["xp"])
    user["level"] = new_level

    # CP — seasonal
    season = data.get("season", {})
    if isinstance(season, dict) and season.get("active"):
        snum = str(season.get("current_season", 1))
        scp  = user.setdefault("season_cp", {})
        if not isinstance(scp, dict):
            user["season_cp"] = {}
            scp = user["season_cp"]
        scp[snum] = int(scp.get(snum, 0)) + cp_gain

    # Check for milestone crossings
    milestone_rewards_list: list[dict] = []
    crossed = [lvl for lvl in LEVEL_MILESTONES if old_level < lvl <= new_level]

    for milestone_level in crossed:
        milestone_dict = LEVEL_MILESTONES[milestone_level]

        # Grant coins
        coins_reward = milestone_dict.get("coins", 0)
        if coins_reward > 0:
            user["balance"] = int(user.get("balance", 0)) + coins_reward

        # Grant gems (premium_balance)
        gems_reward = milestone_dict.get("gems", 0)
        if gems_reward > 0:
            user["premium_balance"] = int(user.get("premium_balance", 0)) + gems_reward

        # Queue pack for granting (use pending_milestone_packs to avoid circular imports)
        pack_key = milestone_dict.get("pack")
        if pack_key:
            pending_packs = user.setdefault("pending_milestone_packs", [])
            if not isinstance(pending_packs, list):
                user["pending_milestone_packs"] = []
                pending_packs = user["pending_milestone_packs"]
            pending_packs.append(pack_key)

        # Add milestone to rewards list with full info
        reward_info = {
            "level": milestone_level,
            "coins": coins_reward,
            "gems": gems_reward,
            "pack": pack_key,
            "message": milestone_dict.get("message", ""),
        }
        milestone_rewards_list.append(reward_info)

    return xp_gain, cp_gain, milestone_rewards_list
