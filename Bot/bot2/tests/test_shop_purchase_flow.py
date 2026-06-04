from __future__ import annotations

from bot.data.defaults import build_default_data, build_default_player
from bot.features.shop import is_public_shop_pack, purchase_shop_pack


def test_war_pack_is_not_public_shop_pack() -> None:
    data = build_default_data()
    war_pack = data["packs"]["definitions"]["war_pack"]

    assert war_pack["enabled"] is False
    assert is_public_shop_pack("war_pack", war_pack) is False


def test_shop_purchase_tracks_global_and_player_spend() -> None:
    data = build_default_data()
    data["players"]["u1"] = build_default_player("u1", "Tester", 123)
    data["players"]["u1"]["user"]["balance"] = 10_000

    ok, reason = purchase_shop_pack(data, "u1", "newbie_pack", 2, 750)

    assert (ok, reason) == (True, "ok")
    assert data["players"]["u1"]["user"]["balance"] == 8_500
    assert data["packs"]["stats"]["total_spent"] == 1_500
    assert data["players"]["u1"]["packs"]["spent"] == 1_500
    assert len(data["players"]["u1"]["user"]["pack_inventory"]) == 2
