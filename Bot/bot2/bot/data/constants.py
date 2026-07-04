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


# ── Battle constants ─────────────────────────────────────────────────────────

# Stamina
STAMINA_BASE: int = 100
STAMINA_COST: dict[str, int] = {
    "normal":       10,
    "special":      20,
    "ultimate":     35,
    "unique_skill": 25,
    "unique_path":  25,
    "block":        15,
    "dodge":        15,
    "parry":        15,
    "revert":       15,
    "tank":         15,
}

# Defense rejection: stat gap above which defense is rejected.
REJECTION_THRESHOLD: int = 30

# Rank trophy thresholds (mirrors _rank_from_trophies in battle_state.py).
TROPHY_THRESHOLD_IRON:     int = 200
TROPHY_THRESHOLD_BRONZE:   int = 400
TROPHY_THRESHOLD_SILVER:   int = 800
TROPHY_THRESHOLD_GOLD:     int = 1200
TROPHY_THRESHOLD_DIAMOND:  int = 1600
TROPHY_THRESHOLD_PLATINUM: int = 2400
TROPHY_THRESHOLD_SAPPHIRE: int = 3200
TROPHY_THRESHOLD_RUBY:     int = 4000

# CPU difficulty star scaling (lower bound, inclusive).
CPU_STAR_TIER_1_MAX:  int = 400   # star_range (1, 2) below this
CPU_STAR_TIER_2_MAX:  int = 1200  # star_range (1, 3) below this
CPU_STAR_TIER_3_MAX:  int = 2400  # star_range (2, 4) below this
                                  # star_range (3, 5) at or above CPU_STAR_TIER_3_MAX

# PvP trophy delta — "same rank" bracket when |trophies_a - trophies_b| <= this.
PVP_SAME_BRACKET_GAP: int = 50

# PvP trophy delta ranges (min, max inclusive).
PVP_SAME_WIN_MIN:   int = 25
PVP_SAME_WIN_MAX:   int = 40
PVP_SAME_DRAW_FLAT: int = 10

PVP_DIFF_DRAW_UNDERDOG_GAIN_MIN:  int = 10
PVP_DIFF_DRAW_UNDERDOG_GAIN_MAX:  int = 20
PVP_DIFF_DRAW_FAVOURITE_LOSS_MIN: int = 0
PVP_DIFF_DRAW_FAVOURITE_LOSS_MAX: int = 10

PVP_DIFF_UPSET_WIN_MIN:    int = 30  # underdog wins
PVP_DIFF_UPSET_WIN_MAX:    int = 50
PVP_DIFF_FAVOURITE_WIN_MIN: int = 20  # favourite wins
PVP_DIFF_FAVOURITE_WIN_MAX: int = 30

# CPU ELO (legacy) — K-factor and elo denominator.
ELO_K_DEFAULT:    int = 22
ELO_K_BELOW_500:  int = 28
ELO_K_ABOVE_2000: int = 16
ELO_DENOMINATOR:  int = 400  # standard Elo scale factor (10^((rating_diff)/400))
ELO_WIN_CLAMP_MAX: int = 22
ELO_WIN_CLAMP_MIN: int = 4
ELO_LOSS_CLAMP_MAX: int = -4
ELO_LOSS_CLAMP_MIN: int = -22

ELO_TP_LOW_THRESHOLD:  int = 500   # below → use ELO_K_BELOW_500
ELO_TP_HIGH_THRESHOLD: int = 2000  # above → use ELO_K_ABOVE_2000

# Anti-farm scaling (recent CPU wins in ANTI_FARM_WINDOW_SECS seconds).
ANTI_FARM_WINDOW_SECS:  int = 600   # 10-minute rolling window
ANTI_FARM_TIER1_WINS:   int = 3     # >= this → 0.5× delta
ANTI_FARM_TIER2_WINS:   int = 6     # >= this → 0.25× delta

# Daily CPU trophy cap.
CPU_DAILY_TROPHY_CAP:  int = 100

# CPU win coin reward range.
WIN_COIN_REWARD_MIN: int = 50
WIN_COIN_REWARD_MAX: int = 90


def rarity_icon(rarity: str | None) -> str:
    return RARITY_ICONS.get(str(rarity or ""), "•")


def rarity_rank(rarity: str | None) -> int:
    r = str(rarity or "")
    return RARITY_RANK.index(r) if r in RARITY_RANK else 0
