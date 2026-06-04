"""Tests for centralized constants — guard against rarity-icon drift."""

from __future__ import annotations

from bot.data.constants import (
    EMBED_COLORS,
    INSTANT_SELL,
    PRICE_RANGES,
    RARITY_ICONS,
    RARITY_RANK,
    rarity_icon,
    rarity_rank,
)


def test_rarity_rank_covers_all_icons() -> None:
    assert set(RARITY_RANK) == set(RARITY_ICONS.keys())
    assert set(RARITY_RANK) == set(PRICE_RANGES.keys())
    assert set(RARITY_RANK) == set(INSTANT_SELL.keys())


def test_legendary_is_orange_not_yellow() -> None:
    # Legacy bug: card_tools.py and cards_admin.py used 🟡; canonical is 🟠
    assert RARITY_ICONS["Legendary"] == "🟠"


def test_rarity_icon_helper_handles_unknown() -> None:
    assert rarity_icon("Common") == "⚪"
    assert rarity_icon("nonsense") == "•"
    assert rarity_icon(None) == "•"


def test_rarity_rank_orders_correctly() -> None:
    assert rarity_rank("Common") < rarity_rank("Abyssal")
    assert rarity_rank("Mythical") < rarity_rank("Infernal")
    assert rarity_rank(None) == 0


def test_price_ranges_are_increasing() -> None:
    prev_max = 0
    for r in RARITY_RANK:
        mn, mx = PRICE_RANGES[r]
        assert mn > 0
        assert mn <= mx
        assert mn >= prev_max
        prev_max = mx


def test_instant_sell_below_min_market_price() -> None:
    for r in RARITY_RANK:
        assert INSTANT_SELL[r] <= PRICE_RANGES[r][0]


def test_embed_colors_are_24bit() -> None:
    for name in ("OK", "ERR", "INFO", "BALANCE", "BATTLE"):
        v = getattr(EMBED_COLORS, name)
        assert 0 <= v <= 0xFFFFFF
