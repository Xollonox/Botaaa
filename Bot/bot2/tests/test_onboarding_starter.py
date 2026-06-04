from __future__ import annotations

from bot.data.defaults import build_default_data, build_default_player
from bot.features.onboarding import STARTER_COINS, ensure_started_player


def _newbie_pack_count(player: dict) -> int:
    return sum(
        1
        for item in player["user"].get("pack_inventory", [])
        if isinstance(item, dict) and item.get("key") == "newbie_pack"
    )


def test_accept_terms_grants_starter_resources_for_new_player() -> None:
    data = build_default_data()

    player, granted = ensure_started_player(data, "u1", "Tester", accept_terms=True)

    assert granted is True
    assert player["user"]["tos_accepted"] is True
    assert player["user"]["starter_granted"] is True
    assert player["user"]["balance"] == STARTER_COINS
    assert _newbie_pack_count(player) == 3


def test_start_grants_starter_after_terms_only_profile() -> None:
    data = build_default_data()
    data["players"]["u1"] = build_default_player("u1", "Tester", 123)
    data["players"]["u1"]["user"]["tos_accepted"] = True

    player, granted = ensure_started_player(data, "u1", "Tester", accept_terms=True)

    assert granted is True
    assert player["user"]["balance"] == STARTER_COINS
    assert _newbie_pack_count(player) == 3


def test_starter_resources_are_not_granted_twice() -> None:
    data = build_default_data()

    ensure_started_player(data, "u1", "Tester", accept_terms=True)
    player, granted = ensure_started_player(data, "u1", "Tester", accept_terms=True)

    assert granted is False
    assert player["user"]["balance"] == STARTER_COINS
    assert _newbie_pack_count(player) == 3
