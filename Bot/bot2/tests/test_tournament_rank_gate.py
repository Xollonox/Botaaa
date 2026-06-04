"""Tests for the tournament min-rank gating logic."""

from __future__ import annotations

from bot.data.constants import RANK_ORDER


def test_rank_order_is_monotonic_and_unique() -> None:
    assert RANK_ORDER == sorted(set(RANK_ORDER), key=RANK_ORDER.index)
    assert RANK_ORDER[0] == "Copper"
    assert RANK_ORDER[-1] == "Ruby"


def _is_eligible(player_rank: str, min_rank: str) -> bool:
    """Mirror of the production gate logic in tournament.py:_join_tournament."""
    if not min_rank or min_rank not in RANK_ORDER:
        return True
    player_tier = RANK_ORDER.index(player_rank) if player_rank in RANK_ORDER else 0
    return player_tier >= RANK_ORDER.index(min_rank)


def test_copper_rejected_from_diamond_tournament() -> None:
    assert not _is_eligible("Copper", "Diamond")


def test_diamond_admitted_to_diamond_tournament() -> None:
    assert _is_eligible("Diamond", "Diamond")


def test_ruby_admitted_to_any_tournament() -> None:
    for r in RANK_ORDER:
        assert _is_eligible("Ruby", r)


def test_empty_min_rank_admits_all() -> None:
    for r in RANK_ORDER:
        assert _is_eligible(r, "")


def test_unknown_min_rank_falls_open() -> None:
    assert _is_eligible("Copper", "Mythic")  # not in RANK_ORDER → no gate
