"""Battle engine helpers and attack type normalization."""

from __future__ import annotations

from typing import Any

from bot.utils.attacks_logic import ATTACK_TYPES, DEFENSE_TYPES

# All valid move types
VALID_MOVE_TYPES = ATTACK_TYPES + DEFENSE_TYPES + ["switch", "forfeit"]


def normalize_attack_type(raw: str) -> str:
    """
    Normalize a raw attack/move type string to a canonical form.

    Returns the normalized type, or 'normal' as a fallback.
    """
    normalized = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in ATTACK_TYPES:
        return normalized
    if normalized in DEFENSE_TYPES:
        return normalized
    if normalized in ("switch", "forfeit"):
        return normalized
    # Partial match
    for t in ATTACK_TYPES + DEFENSE_TYPES:
        if normalized in t or t in normalized:
            return t
    return "normal"


def calc_damage(
    attacker_stats: dict[str, int],
    defender_stats: dict[str, int],
    attack_type: str,
    attack_power: int = 0,
) -> int:
    """Calculate damage for an attack."""
    # Primary stats per attack type
    stat_map = {
        "normal": "strength",
        "special": "technique",
        "ultimate": "battle_iq",
        "unique_skill": "technique",
        "unique_path": "iq",
    }
    primary_stat = stat_map.get(attack_type, "strength")
    atk = int(attacker_stats.get(primary_stat, 0))
    defense = int(defender_stats.get("endurance", 0))
    base_power = max(1, attack_power)
    raw_damage = int(atk * base_power / max(1, defense) * 0.5) + int(base_power * 0.3)
    return max(1, raw_damage)


def calc_defense_reduction(defense_type: str, incoming_damage: int) -> int:
    """Calculate damage after defense action."""
    if defense_type == "block":
        return max(0, int(incoming_damage * 0.4))
    elif defense_type == "dodge":
        # 50% chance to dodge fully
        import random
        return 0 if random.random() < 0.5 else incoming_damage
    elif defense_type == "parry":
        # Parry reduces and counter-damages
        return max(0, int(incoming_damage * 0.2))
    elif defense_type == "revert":
        # Revert heals based on damage
        return max(0, int(incoming_damage * 0.6))
    return incoming_damage
