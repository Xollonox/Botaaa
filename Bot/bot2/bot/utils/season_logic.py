"""Season and season pass logic."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LEAGUE_ORDER = [
    "Copper", "Iron", "Bronze", "Silver", "Gold", "Diamond", "Platinum", "Sapphire", "Ruby",
]

XP_PER_LEVEL = 100


def ensure_season_data(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure season_data structure exists and return it."""
    sd = data.get("season_data")
    if not isinstance(sd, dict):
        from bot.data.defaults import DEFAULT_DATA
        data["season_data"] = deepcopy(DEFAULT_DATA["season_data"])
    else:
        sd.setdefault("current_season", 1)
        sd.setdefault("start_time", 0)
        sd.setdefault("end_time", 0)
        sd.setdefault("reset_type", "soft")
        sd.setdefault("soft_reset_percent", 50)
        sd.setdefault("global_rewards", [])
        sd.setdefault("season_rewards", {})
        sd.setdefault("season_reward_distributed", False)
        sd.setdefault("archived_seasons", {})
        sd.setdefault("season_pass_rewards", {})
    return data["season_data"]


def level_from_xp(xp: int) -> int:
    """Return the level for the given XP."""
    return max(1, int(xp) // XP_PER_LEVEL + 1)


def xp_for_next_level(xp: int) -> int:
    """Return XP needed to reach the next level."""
    current_level = level_from_xp(xp)
    next_level_xp = current_level * XP_PER_LEVEL
    return max(0, next_level_xp - int(xp))


def ensure_player_pass(player: dict[str, Any], current_season: int) -> dict[str, Any]:
    """Ensure a player has a season pass entry for the current season."""
    sp = player.get("season_pass")
    if not isinstance(sp, dict):
        sp = {"season": current_season, "xp": 0, "level": 1, "claimed": {}}
        player["season_pass"] = sp
    if int(sp.get("season", 0)) != current_season:
        sp["season"] = current_season
        sp["xp"] = 0
        sp["level"] = 1
        sp["claimed"] = {}
    sp.setdefault("claimed", {})
    return sp


def add_season_pass_xp(player: dict[str, Any], amount: int, current_season: int) -> tuple[int, int]:
    """Add XP to the player's season pass. Returns (new_xp, new_level)."""
    sp = ensure_player_pass(player, current_season)
    new_xp = int(sp.get("xp", 0)) + int(amount)
    sp["xp"] = new_xp
    new_level = level_from_xp(new_xp)
    sp["level"] = new_level
    return new_xp, new_level


def league_meets(player_rank: str, required_rank: str) -> bool:
    """Return True if *player_rank* meets or exceeds *required_rank*."""
    ranks = LEAGUE_ORDER
    try:
        p_idx = ranks.index(player_rank)
    except ValueError:
        p_idx = 0
    try:
        r_idx = ranks.index(required_rank)
    except ValueError:
        r_idx = 0
    return p_idx >= r_idx


def is_reward_eligible(
    data: dict[str, Any],
    player: dict[str, Any],
    reward_entry: dict[str, Any],
) -> bool:
    """Check if a player is eligible to claim a season reward."""
    required_rank = str(reward_entry.get("required_rank", "Copper"))
    player_rank = str(player.get("user", {}).get("rank", "Copper"))
    return league_meets(player_rank, required_rank)


def is_reward_claimed(player: dict[str, Any], reward_id: str, season: int) -> bool:
    """Return True if the player has already claimed this season reward."""
    claims = player.get("season_claims", {})
    if not isinstance(claims, dict):
        return False
    season_key = str(season)
    season_claims = claims.get(season_key, {})
    if not isinstance(season_claims, dict):
        return False
    return bool(season_claims.get(str(reward_id), False))


def mark_reward_claimed(player: dict[str, Any], reward_id: str, season: int) -> None:
    """Mark a season reward as claimed."""
    claims = player.setdefault("season_claims", {})
    if not isinstance(claims, dict):
        claims = {}
        player["season_claims"] = claims
    season_key = str(season)
    season_claims = claims.setdefault(season_key, {})
    if not isinstance(season_claims, dict):
        season_claims = {}
        claims[season_key] = season_claims
    season_claims[str(reward_id)] = True


def archive_current_season(data: dict[str, Any], now: int) -> int:
    """Archive the current season and bump the season counter. Returns the new season number."""
    sd = ensure_season_data(data)
    current = int(sd.get("current_season", 1))

    archived = sd.setdefault("archived_seasons", {})
    if not isinstance(archived, dict):
        archived = {}
        sd["archived_seasons"] = archived

    archived[str(current)] = {
        "season": current,
        "archived_at": now,
        "start_time": sd.get("start_time", 0),
        "end_time": sd.get("end_time", 0),
    }

    new_season = current + 1
    sd["current_season"] = new_season
    sd["start_time"] = now
    sd["end_time"] = 0
    sd["season_reward_distributed"] = False
    return new_season


def apply_season_reset_to_players(
    data: dict[str, Any],
    reset_type: str,
    soft_reset_percent: int,
) -> int:
    """Apply season reset to all players. Returns number of players affected."""
    players = data.get("players", {})
    if not isinstance(players, dict):
        return 0

    count = 0
    for player in players.values():
        if not isinstance(player, dict):
            continue
        user = player.get("user", {})
        if not isinstance(user, dict):
            continue

        if reset_type == "hard":
            user["trophies"] = 0
            user["rank"] = "Copper"
        elif reset_type == "soft":
            trophies = int(user.get("trophies", 0))
            new_trophies = int(trophies * soft_reset_percent / 100)
            user["trophies"] = new_trophies
            # Recalculate rank
            user["rank"] = _rank_from_trophies(new_trophies)

        # Reset ranked stats
        player["ranked_stats"] = {"wins": 0, "losses": 0, "streak": 0, "last_10": []}
        count += 1

    return count


def _rank_from_trophies(trophies: int) -> str:
    """Return a league rank based on trophy count.

    Must mirror bot.utils.battle_state._rank_from_trophies — the ground truth.
    """
    if trophies >= 4000:
        return "Ruby"
    if trophies >= 3200:
        return "Sapphire"
    if trophies >= 2400:
        return "Platinum"
    if trophies >= 1600:
        return "Diamond"
    if trophies >= 1200:
        return "Gold"
    if trophies >= 800:
        return "Silver"
    if trophies >= 400:
        return "Bronze"
    if trophies >= 200:
        return "Iron"
    return "Copper"
