"""Reward configuration helpers for rarity drop rates."""

from __future__ import annotations

from typing import Any

from bot.utils.cards_logic import RARITIES

RATE_RARITIES = ["Common", "Rare", "Epic", "Legendary", "Mythical", "Infernal", "Abyssal"]


def build_rates(
    common: int | None = None,
    rare: int | None = None,
    epic: int | None = None,
    legendary: int | None = None,
    mythical: int | None = None,
    infernal: int | None = None,
    abyssal: int | None = None,
) -> dict[str, int]:
    """Build a rates dict from individual rarity values (None = 0)."""
    return {
        "Common": int(common or 0),
        "Rare": int(rare or 0),
        "Epic": int(epic or 0),
        "Legendary": int(legendary or 0),
        "Mythical": int(mythical or 0),
        "Infernal": int(infernal or 0),
        "Abyssal": int(abyssal or 0),
    }


def validate_rates(rates: dict[str, int]) -> tuple[bool, str]:
    """Validate a rates dict. All values must be >= 0."""
    if not isinstance(rates, dict):
        return False, "Rates must be a dict."
    for rarity, value in rates.items():
        if rarity not in RARITIES:
            return False, f"Unknown rarity '{rarity}'."
        if not isinstance(value, int) or value < 0:
            return False, f"Rate for '{rarity}' must be a non-negative integer."
    return True, "OK"


def format_rates_block(rates: dict[str, int]) -> str:
    """Format a rates dict as a display string."""
    if not isinstance(rates, dict):
        return "No rates configured."
    lines = []
    for rarity in RATE_RARITIES:
        val = int(rates.get(rarity, 0))
        if val > 0:
            lines.append(f"{rarity}: {val}")
    return "\n".join(lines) if lines else "All rates are 0."
