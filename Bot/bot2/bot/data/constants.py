"""Centralized constants — single source of truth for icons, prices, colors."""

from __future__ import annotations

RARITY_RANK: list[str] = [
    "Common", "Rare", "Epic", "Legendary", "Mythical", "Infernal", "Abyssal",
]

# Player rank tiers, ordered low → high. Mirrors _rank_from_trophies in battle_state.py.
RANK_ORDER: list[str] = [
    "Copper", "Iron", "Bronze", "Silver", "Gold", "Diamond", "Platinum", "Sapphire", "Ruby",
]

RARITY_ICONS: dict[str, str] = {
    "Common":    "⚪",
    "Rare":      "🔵",
    "Epic":      "🟣",
    "Legendary": "🟠",
    "Mythical":  "🔴",
    "Infernal":  "🔥",
    "Abyssal":   "🌌",
}

PRICE_RANGES: dict[str, tuple[int, int]] = {
    "Common":    (500,    1_000),
    "Rare":      (3_000,  5_000),
    "Epic":      (10_000, 20_000),
    "Legendary": (30_000, 40_000),
    "Mythical":  (50_000, 60_000),
    "Infernal":  (70_000, 80_000),
    "Abyssal":   (90_000, 100_000),
}

INSTANT_SELL: dict[str, int] = {
    "Common":    250,
    "Rare":      1_000,
    "Epic":      5_000,
    "Legendary": 20_000,
    "Mythical":  40_000,
    "Infernal":  60_000,
    "Abyssal":   80_000,
}


class EMBED_COLORS:
    OK      = 0x2ECC71
    ERR     = 0xE74C3C
    INFO    = 0x3498DB
    BALANCE = 0xE11D48
    BATTLE  = 0x2b2d31


def rarity_icon(rarity: str | None) -> str:
    return RARITY_ICONS.get(str(rarity or ""), "•")


def rarity_rank(rarity: str | None) -> int:
    r = str(rarity or "")
    return RARITY_RANK.index(r) if r in RARITY_RANK else 0
