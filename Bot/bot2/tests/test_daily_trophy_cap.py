"""Tests for the daily +100 trophy cap from CPU wins."""

from __future__ import annotations

from bot.utils.battle_state import _resolve_cpu_outcome


def _player(uid: str, trophies: int = 500) -> dict:
    return {
        "user": {
            "balance": 0,
            "trophies": trophies,
            "rank": "Bronze",
        },
    }


def _build_state(now: int, cpu_trophies: int = 500) -> dict:
    return {
        "turn_started_at": now,
        "players": {
            "cpu_id": {
                "is_cpu": True,
                "cpu_meta": {"display_name": "CPU", "personality": "Balanced", "trophies": cpu_trophies},
            },
        },
    }


def test_daily_cap_blocks_excess_trophy_gain() -> None:
    now = 1_700_000_000  # arbitrary fixed ts
    data = {"players": {"u1": _player("u1", trophies=500)}}
    state = _build_state(now)

    total_actual_gain = 0
    for _ in range(50):
        before = int(data["players"]["u1"]["user"]["trophies"])
        _resolve_cpu_outcome(state, data, "u1", "u1")
        after = int(data["players"]["u1"]["user"]["trophies"])
        total_actual_gain += (after - before)

    assert total_actual_gain == 100
    assert int(data["players"]["u1"]["user"]["daily_cpu_trophy_sum"]) == 100


def test_daily_cap_resets_at_utc_midnight() -> None:
    day1 = 1_700_000_000
    day2 = day1 + 86400 + 60  # well into next UTC day
    data = {"players": {"u1": _player("u1", trophies=500)}}

    state = _build_state(day1)
    for _ in range(30):
        _resolve_cpu_outcome(state, data, "u1", "u1")
    after_day1 = int(data["players"]["u1"]["user"]["trophies"])

    # Roll over a day.
    state["turn_started_at"] = day2
    state["players"]["cpu_id"]["cpu_meta"]["trophies"] = 500
    # Reset 10-min anti-farm too (it's already pruned, but kill the list).
    data["players"]["u1"]["user"]["cpu_win_timestamps"] = []

    for _ in range(30):
        _resolve_cpu_outcome(state, data, "u1", "u1")
    after_day2 = int(data["players"]["u1"]["user"]["trophies"])

    # Day 2 must add at least 1 more trophy beyond the day-1 ceiling.
    assert after_day2 > after_day1
    # Day 2's bucket should be capped at 100 again.
    assert int(data["players"]["u1"]["user"]["daily_cpu_trophy_sum"]) <= 100


def test_loss_does_not_increment_daily_sum() -> None:
    now = 1_700_000_000
    data = {"players": {"u1": _player("u1", trophies=500)}}
    state = _build_state(now)

    _resolve_cpu_outcome(state, data, "u1", "cpu_id")  # CPU wins → human loss
    assert int(data["players"]["u1"]["user"].get("daily_cpu_trophy_sum", 0)) == 0
