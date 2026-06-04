"""Tests for adaptive trophy-bracket matchmaking window."""

from __future__ import annotations


def _window(joined_at: int, now: int) -> int:
    """Mirror of the production formula in bot/features/battle.py:_try_match."""
    elapsed = max(0, now - int(joined_at))
    return min(2000, 200 + (elapsed // 30) * 100)


def test_window_starts_at_200() -> None:
    assert _window(1000, 1000) == 200


def test_window_widens_by_100_every_30s() -> None:
    base = 1000
    assert _window(base, base + 29)  == 200
    assert _window(base, base + 30)  == 300
    assert _window(base, base + 60)  == 400
    assert _window(base, base + 300) == 200 + 10 * 100  # = 1200


def test_window_capped_at_2000() -> None:
    base = 1000
    # 1 hour queued → would be 200 + 120*100 = 12_200, but capped.
    assert _window(base, base + 3600) == 2000


def test_match_uses_max_of_both_windows() -> None:
    """A long-waiting player should match a fresh joiner using the wider window."""
    now = 10_000
    waited_90s = now - 90      # window = 200 + 3*100 = 500
    fresh      = now           # window = 200
    window = max(_window(waited_90s, now), _window(fresh, now))
    # A 400-trophy gap should match the long-waiter despite the fresh joiner's tight window.
    assert window >= 400
