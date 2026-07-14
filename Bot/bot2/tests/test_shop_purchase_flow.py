from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.data.defaults import build_default_data, build_default_player
from bot.features.shop import ShopPages, is_public_shop_pack, purchase_shop_pack


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


def _shop_view() -> ShopPages:
    storage = SimpleNamespace(load=MagicMock(return_value={"players": {}}))
    cog = SimpleNamespace(bot=SimpleNamespace(storage=storage))
    return ShopPages(cog, "123", [], "Shop")


def test_shop_component_defers_before_rebuilding_and_loading() -> None:
    events: list[str] = []
    view = _shop_view()
    view._rebuild_selects = MagicMock(side_effect=lambda: events.append("rebuild"))
    view.cog.bot.storage.load = MagicMock(side_effect=lambda: events.append("load") or {"players": {}})
    view.embed = MagicMock(return_value=discord.Embed(title="Shop"))

    response = SimpleNamespace(
        is_done=lambda: False,
        defer=AsyncMock(side_effect=lambda: events.append("defer")),
    )
    interaction = SimpleNamespace(
        response=response,
        user=SimpleNamespace(id=123),
        message=SimpleNamespace(id=456),
        edit_original_response=AsyncMock(side_effect=lambda **_: events.append("edit")),
    )

    assert asyncio.run(view._refresh_component(interaction)) is True
    assert events == ["defer", "rebuild", "load", "edit"]


def test_shop_component_stops_view_when_interaction_expired() -> None:
    view = _shop_view()
    response = MagicMock(status=404, reason="Not Found", headers={})
    expired = discord.NotFound(response, {"code": 10062, "message": "Unknown interaction"})
    interaction = SimpleNamespace(
        response=SimpleNamespace(is_done=lambda: False, defer=AsyncMock(side_effect=expired)),
        user=SimpleNamespace(id=123),
        message=SimpleNamespace(id=456),
        edit_original_response=AsyncMock(),
    )
    view.stop = MagicMock()

    assert asyncio.run(view._refresh_component(interaction)) is False
    view.stop.assert_called_once_with()
    interaction.edit_original_response.assert_not_awaited()
