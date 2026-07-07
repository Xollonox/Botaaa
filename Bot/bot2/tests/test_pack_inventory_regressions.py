from __future__ import annotations

from bot.data.defaults import build_default_data, build_default_player
from bot.features.packs import _open_pack_from_inventory
from bot.utils.reward_grant import grant_reward


def test_pack_reward_uses_openable_pack_inventory() -> None:
    data = build_default_data()
    data["players"]["u1"] = build_default_player("u1", "Tester", 123)

    ok, message = grant_reward(
        data,
        "u1",
        {"reward_type": "pack", "reward_value": "newbie_pack"},
        now=123,
    )

    assert ok is True
    assert message == "Granted pack 'newbie_pack'."
    user = data["players"]["u1"]["user"]
    assert user.get("owned_packs", {}) == {}
    assert [item["key"] for item in user["pack_inventory"]] == ["newbie_pack"]


def test_failed_pack_open_does_not_consume_pack() -> None:
    data = build_default_data()
    data["players"]["u1"] = build_default_player("u1", "Tester", 123)
    user = data["players"]["u1"]["user"]
    user["pack_inventory"] = [{"key": "missing_pack", "name": "Missing Pack", "acquired_at": 123}]

    ok, reason, rolls = _open_pack_from_inventory(data, "u1", "missing_pack")

    assert (ok, reason, rolls) == (False, "pack_not_found", [])
    assert user["pack_inventory"] == [{"key": "missing_pack", "name": "Missing Pack", "acquired_at": 123}]


def test_open_pack_from_reward_inventory_grants_card() -> None:
    data = build_default_data()
    data["players"]["u1"] = build_default_player("u1", "Tester", 123)
    grant_reward(data, "u1", {"reward_type": "pack", "reward_value": "newbie_pack"}, now=123)

    ok, reason, rolls = _open_pack_from_inventory(data, "u1", "newbie_pack")

    assert ok is True
    assert reason == "ok"
    assert rolls
    user = data["players"]["u1"]["user"]
    assert user["pack_inventory"] == []
    assert len(user["inventory"]) == len(rolls)
