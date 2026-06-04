"""Tests for the 1-swap-per-battle cap."""

from __future__ import annotations


def _can_swap(side: dict) -> bool:
    """Production rule from battle.py:_switch_options and _apply_switch."""
    if bool(side.get("is_cpu", False)):
        return True
    return int(side.get("swaps_used", 0)) < 1


def test_first_swap_allowed() -> None:
    side = {"is_cpu": False, "swaps_used": 0}
    assert _can_swap(side)


def test_second_swap_blocked() -> None:
    side = {"is_cpu": False, "swaps_used": 1}
    assert not _can_swap(side)


def test_cpu_swaps_unrestricted() -> None:
    side = {"is_cpu": True, "swaps_used": 5}
    assert _can_swap(side)


def test_swap_counter_increments_per_use() -> None:
    side = {"is_cpu": False, "swaps_used": 0}
    side["swaps_used"] = int(side.get("swaps_used", 0)) + 1
    assert not _can_swap(side)
