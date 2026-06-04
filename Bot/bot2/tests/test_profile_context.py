"""Tests for profile card data extraction helpers."""

from __future__ import annotations

from types import SimpleNamespace

from bot.features.profile_render import _profile_card_context


def test_profile_card_context_calculates_rank_and_win_rate() -> None:
    target = SimpleNamespace(id=2, display_name="Jane", name="Jane", display_avatar=SimpleNamespace(url=None))
    data = {
        "players": {
            "1": {"user": {"trophies": 200}},
            "2": {
                "user": {
                    "trophies": 100,
                    "rank": "Copper",
                    "profile": {"bio": "hello"},
                    "inventory": [{"uid": "a"}],
                },
                "ranked_stats": {"wins": 3, "losses": 1, "streak": 2},
            },
        }
    }

    ctx = _profile_card_context(data, target)

    assert ctx["target_id"] == "2"
    assert ctx["global_rank"] == 2
    assert ctx["cards_unlocked"] == 1
    assert ctx["battles_played"] == 4
    assert ctx["win_rate"] == 75.0
