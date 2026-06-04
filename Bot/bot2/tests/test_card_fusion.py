"""Tests for /fuse card fusion logic — 3 copies → +1 star, max 5."""

from __future__ import annotations


def _fuse_mutate(data: dict, user_id: str, target: str) -> tuple[str, dict]:
    """In-test reproduction of the production mutate in card_tools.py:fuse.

    Kept structurally identical so a drift between the two is caught by review.
    """
    player = data.get("players", {}).get(user_id, {})
    user   = player.get("user", {}) if isinstance(player, dict) else {}
    inv    = user.get("inventory", []) if isinstance(user, dict) else []
    if not isinstance(inv, list):
        return "no_inventory", {}

    matches: list[tuple[int, dict]] = []
    for idx, item in enumerate(inv):
        if not isinstance(item, dict):
            continue
        if str(item.get("card_name", "")).lower() != target.lower():
            continue
        if item.get("locked") or item.get("squad_locked") or item.get("market_locked") or item.get("trade_locked"):
            continue
        matches.append((idx, item))

    if len(matches) < 3:
        return "need_three", {"have": len(matches)}

    matches.sort(key=lambda p: int(p[1].get("stars", 0)), reverse=True)
    primary_idx, primary = matches[0]
    sacrifice_idxs = sorted([matches[1][0], matches[2][0]], reverse=True)

    cur_stars = int(primary.get("stars", 0))
    if cur_stars >= 5:
        return "max_stars", {"card_name": str(primary.get("card_name", target))}

    for i in sacrifice_idxs:
        if i == primary_idx:
            continue
        inv.pop(i)
        if i < primary_idx:
            primary_idx -= 1

    inv[primary_idx]["stars"] = min(5, cur_stars + 1)
    return "ok", {"stars": int(inv[primary_idx]["stars"])}


def _card(name: str, stars: int = 0, **flags) -> dict:
    return {"card_name": name, "rarity": "Common", "uid": f"{name}-{stars}", "stars": stars, **flags}


def _data(inv: list) -> dict:
    return {"players": {"u1": {"user": {"inventory": inv}}}}


def test_three_copies_consume_two_and_add_one_star() -> None:
    inv = [_card("X"), _card("X"), _card("X")]
    data = _data(inv)
    result, info = _fuse_mutate(data, "u1", "X")
    assert result == "ok"
    assert info["stars"] == 1
    assert len(inv) == 1


def test_two_copies_returns_need_three() -> None:
    inv = [_card("X"), _card("X")]
    data = _data(inv)
    result, info = _fuse_mutate(data, "u1", "X")
    assert result == "need_three"
    assert info["have"] == 2


def test_locked_copies_excluded() -> None:
    inv = [_card("X"), _card("X", squad_locked=True), _card("X", locked=True)]
    data = _data(inv)
    result, _ = _fuse_mutate(data, "u1", "X")
    assert result == "need_three"


def test_max_stars_rejects_fusion() -> None:
    inv = [_card("X", stars=5), _card("X"), _card("X")]
    data = _data(inv)
    result, _ = _fuse_mutate(data, "u1", "X")
    assert result == "max_stars"
    # Inventory must not be mutated on rejection.
    assert len(inv) == 3


def test_primary_picks_highest_stars() -> None:
    inv = [_card("X", stars=2), _card("X", stars=0), _card("X", stars=1)]
    data = _data(inv)
    result, info = _fuse_mutate(data, "u1", "X")
    assert result == "ok"
    assert info["stars"] == 3
    # Surviving card should be the originally-2-star one, now 3-star.
    assert len(inv) == 1
    assert int(inv[0]["stars"]) == 3
