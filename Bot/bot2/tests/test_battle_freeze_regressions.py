from __future__ import annotations

from bot.features.battle import BattleCog
from bot.features.battle_views import TurnView
from bot.utils import battle_state


def _fighter(uid: str, card_name: str) -> dict:
    return {
        "uid": uid,
        "card_name": card_name,
        "stars": 1,
        "assigned_attacks": {"normal": ["jab"]},
    }


def _battle_data() -> dict:
    card = {
        "rarity": "Common",
        "stats": {
            "strength": 20,
            "speed": 20,
            "endurance": 100,
            "technique": 20,
            "iq": 20,
            "battle_iq": 20,
        },
        "moves": {"normal": ["jab"]},
    }
    return {
        "cards": {"A": card, "B": card},
        "players": {
            "u1": {"user": {"inventory": [_fighter("a1", "A")]}},
            "u2": {"user": {"inventory": [_fighter("b1", "B")]}},
        },
        "battle": {"queue": [], "pending_friendly": {}, "active": {}, "active_by_user": {}},
    }


def test_apply_move_sets_real_turn_timestamp(monkeypatch) -> None:
    data = _battle_data()
    battle_id = battle_state.create_battle_state(data, "ranked", "u1", "u2", ["a1"], ["b1"], 1_000)

    monkeypatch.setattr(battle_state, "now_ts", lambda: 2_000)
    result = battle_state.apply_move(data, battle_id, "u1", "normal", "jab")

    assert result["ok"] is True
    assert data["battle"]["active"][battle_id]["turn_started_at"] == 2_000


def test_friendly_timeout_cpu_handler_exists() -> None:
    assert callable(getattr(BattleCog, "_friendly_timeout_to_cpu", None))


def test_turn_view_does_not_have_discord_timeout() -> None:
    view = TurnView(object(), "battle-1", "u1", [], [], [])  # type: ignore[arg-type]

    assert view.timeout is None
