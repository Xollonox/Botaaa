"""Tests for trade validation, locking, and helper logic."""

from __future__ import annotations

from bot.features.trade_views import (
    TRADE_PRICE_BANDS,
    _find_card,
    _lock,
    _remove_card,
    _trade_root,
    _unlock,
    _validate,
)
from bot.features.trades import _board_tradeable


def _card(name: str, rarity: str, uid: str = "u") -> dict:
    return {"card_name": name, "rarity": rarity, "uid": uid}


def test_validate_rejects_empty_offer() -> None:
    ok, _ = _validate(None, None, None, None)
    assert not ok


def test_validate_rejects_coins_for_coins() -> None:
    ok, msg = _validate(None, 1000, None, 1000)
    assert not ok
    assert "coins for coins" in msg.lower()


def test_validate_requires_matching_rarity_card_for_card() -> None:
    a = _card("X", "Epic")
    b = _card("Y", "Rare")
    ok, msg = _validate(a, None, b, None)
    assert not ok
    assert "rarity" in msg.lower()


def test_validate_accepts_matching_rarity_card_for_card() -> None:
    a = _card("X", "Epic")
    b = _card("Y", "Epic")
    ok, _ = _validate(a, None, b, None)
    assert ok


def test_validate_enforces_price_band_for_card_for_coins() -> None:
    rare_card = _card("X", "Rare")
    mn, mx = TRADE_PRICE_BANDS["Rare"]
    ok, _ = _validate(rare_card, None, None, mn - 1)
    assert not ok
    ok, _ = _validate(rare_card, None, None, mx + 1)
    assert not ok
    ok, _ = _validate(rare_card, None, None, mn)
    assert ok


def test_lock_and_unlock_flag_only_target_uid() -> None:
    inv = [{"uid": "a"}, {"uid": "b"}]
    _lock(inv, "a")
    assert inv[0].get("trade_locked") is True
    assert "trade_locked" not in inv[1]
    _unlock(inv, "a")
    assert inv[0].get("trade_locked") is False


def test_find_card_skips_locked() -> None:
    inv = [
        {"card_name": "X", "uid": "1", "trade_locked": True},
        {"card_name": "X", "uid": "2"},
    ]
    found = _find_card(inv, "X")
    assert found is not None
    assert found["uid"] == "2"


def test_remove_card_returns_and_removes() -> None:
    inv = [{"uid": "a"}, {"uid": "b"}]
    out = _remove_card(inv, "a")
    assert out == {"uid": "a"}
    assert inv == [{"uid": "b"}]
    assert _remove_card(inv, "missing") is None


def test_trade_root_initializes_keys() -> None:
    data: dict = {}
    t = _trade_root(data)
    assert t["pending"] == {}
    assert t["history"] == []
    assert data["trades"] is t


def test_board_trade_rejects_every_lock_type() -> None:
    assert _board_tradeable({"uid": "free"})
    for flag in ("locked", "squad_locked", "market_locked", "trade_locked"):
        assert not _board_tradeable({"uid": flag, flag: True})
