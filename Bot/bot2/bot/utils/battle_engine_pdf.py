"""Battle engine helpers and attack type normalization.

The real battle damage pipeline lives in bot/utils/battle_state.py. The
``calc_*`` helpers below are kept as lightweight compatibility helpers for
formula smoke tests and non-runtime callers.
"""

from __future__ import annotations

import random
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
    attacker_stats: dict[str, Any],
    defender_stats: dict[str, Any],
    *,
    attack_type: str = "normal",
    attack_power: int = 10,
) -> int:
    """Compatibility damage estimate for tests; runtime uses battle_state."""
    move_type = normalize_attack_type(attack_type)
    if move_type == "unique_skill":
        attack_stat = int(attacker_stats.get("battle_iq", attacker_stats.get("strength", 0)) or 0)
    elif move_type in {"special", "unique_skill", "unique_path"}:
        attack_stat = int(attacker_stats.get("technique", attacker_stats.get("strength", 0)) or 0)
    else:
        attack_stat = int(attacker_stats.get("strength", 0) or 0)

    endurance = max(0, int(defender_stats.get("endurance", 0) or 0))
    power = max(1, int(attack_power or 0))
    raw = power + max(0, attack_stat // 5)
    reduction = min(0.85, endurance / 1000.0)
    return max(1, int(round(raw * (1.0 - reduction))))


def calc_defense_reduction(defense_type: str, damage: int, *, _rng: random.Random | None = None) -> int:
    """Compatibility defense estimate for tests; runtime uses battle_state.

    Pass a seeded ``_rng`` in tests to make the dodge branch deterministic.
    """
    base = max(0, int(damage or 0))
    defense = normalize_attack_type(defense_type)
    if defense == "block":
        return max(0, int(base * 0.4))
    if defense == "parry":
        return max(0, int(base * 0.2))
    if defense == "revert":
        return max(0, int(base * 0.6))
    if defense == "dodge":
        rng = _rng or random
        return 0 if rng.random() < 0.5 else base
    return base
