"""Battle engine helpers and attack type normalization.

NOTE: calc_damage and calc_defense_reduction were removed — they used wrong formulas.
The real damage pipeline lives in bot/utils/battle_state.py.
"""

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
