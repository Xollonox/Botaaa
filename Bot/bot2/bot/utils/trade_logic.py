"""Trade logic helpers."""

from __future__ import annotations

import uuid
from typing import Any

TRADE_TTL = 86400  # 24 hours


def ensure_trade_structure(data: dict[str, Any]) -> None:
    """Ensure trades structure exists in data."""
    trades = data.get("trades")
    if not isinstance(trades, dict):
        data["trades"] = {"pending": {}}
    else:
        trades.setdefault("pending", {})
        if not isinstance(trades["pending"], dict):
            trades["pending"] = {}


def create_trade_obj(
    initiator_id: str,
    target_id: str,
    offer_uids: list[str],
    request_uids: list[str],
    now: int,
) -> dict[str, Any]:
    """Create a trade object dict."""
    return {
        "trade_id": str(uuid.uuid4()),
        "initiator_id": str(initiator_id),
        "target_id": str(target_id),
        "offer_uids": list(offer_uids),
        "request_uids": list(request_uids),
        "created_at": int(now),
        "status": "pending",
    }


def describe_trade(
    data: dict[str, Any],
    trade: dict[str, Any],
) -> str:
    """Return a human-readable description of a trade."""
    initiator_id = str(trade.get("initiator_id", "?"))
    target_id = str(trade.get("target_id", "?"))
    offer = trade.get("offer_uids", [])
    request = trade.get("request_uids", [])

    players = data.get("players", {})
    def get_name(uid: str) -> str:
        p = players.get(uid, {}) if isinstance(players, dict) else {}
        u = p.get("user", {}) if isinstance(p, dict) else {}
        return str(u.get("name", uid)) if isinstance(u, dict) else uid

    offers_str = ", ".join(str(u)[:8] for u in offer) if offer else "nothing"
    requests_str = ", ".join(str(u)[:8] for u in request) if request else "nothing"

    return (
        f"{get_name(initiator_id)} offers [{offers_str}] "
        f"for [{requests_str}] from {get_name(target_id)}"
    )


def expire_trades(data: dict[str, Any], now: int) -> int:
    """Mark expired pending trades and return the count expired."""
    ensure_trade_structure(data)
    pending = data["trades"]["pending"]
    expired = []
    for tid, trade in pending.items():
        if not isinstance(trade, dict):
            continue
        created = int(trade.get("created_at", 0))
        if now - created > TRADE_TTL:
            expired.append(tid)
    for tid in expired:
        pending[tid]["status"] = "expired"
    return len(expired)


def _transfer_cards(
    data: dict[str, Any],
    from_id: str,
    to_id: str,
    uids: list[str],
) -> bool:
    """Transfer card UIDs from one player to another. Returns True if all found."""
    players = data.get("players", {})
    from_player = players.get(str(from_id)) if isinstance(players, dict) else None
    to_player = players.get(str(to_id)) if isinstance(players, dict) else None
    if not isinstance(from_player, dict) or not isinstance(to_player, dict):
        return False

    from_user = from_player.get("user", {})
    to_user = to_player.get("user", {})
    if not isinstance(from_user, dict) or not isinstance(to_user, dict):
        return False

    from_inv = from_user.get("inventory", [])
    to_inv = to_user.setdefault("inventory", [])
    if not isinstance(from_inv, list) or not isinstance(to_inv, list):
        return False

    for uid in uids:
        idx = next(
            (i for i, item in enumerate(from_inv) if isinstance(item, dict) and str(item.get("uid", "")) == uid),
            None,
        )
        if idx is None:
            return False
        item = from_inv.pop(idx)
        # Reset lock flags
        item["locked"] = False
        item["market_locked"] = False
        item["squad_locked"] = False
        to_inv.append(item)
    return True


def complete_trade_atomic(data: dict[str, Any], trade_id: str, now: int) -> tuple[bool, str]:
    """
    Complete a pending trade atomically.

    Returns (success, message).
    """
    ensure_trade_structure(data)
    pending = data["trades"]["pending"]
    trade = pending.get(str(trade_id))
    if not isinstance(trade, dict):
        return False, "trade_not_found"
    if str(trade.get("status", "")) != "pending":
        return False, f"trade_status_{trade.get('status', 'unknown')}"

    initiator_id = str(trade.get("initiator_id", ""))
    target_id = str(trade.get("target_id", ""))
    offer_uids = trade.get("offer_uids", [])
    request_uids = trade.get("request_uids", [])

    # Transfer offer cards from initiator to target
    if offer_uids:
        if not _transfer_cards(data, initiator_id, target_id, offer_uids):
            return False, "offer_transfer_failed"

    # Transfer request cards from target to initiator
    if request_uids:
        if not _transfer_cards(data, target_id, initiator_id, request_uids):
            # Rollback: return offer cards to initiator
            if offer_uids:
                _transfer_cards(data, target_id, initiator_id, offer_uids)
            return False, "request_transfer_failed"

    trade["status"] = "completed"
    trade["completed_at"] = now

    # Record in trade history
    for uid in (initiator_id, target_id):
        players = data.get("players", {})
        player = players.get(str(uid)) if isinstance(players, dict) else None
        if isinstance(player, dict):
            history = player.setdefault("trade_history", [])
            if isinstance(history, list):
                history.append({"trade_id": str(trade_id), "completed_at": now})

    return True, "Trade completed."


def decline_trade_atomic(data: dict[str, Any], trade_id: str) -> tuple[bool, str]:
    """Decline a pending trade."""
    ensure_trade_structure(data)
    pending = data["trades"]["pending"]
    trade = pending.get(str(trade_id))
    if not isinstance(trade, dict):
        return False, "trade_not_found"
    if str(trade.get("status", "")) != "pending":
        return False, "trade_not_pending"
    trade["status"] = "declined"
    return True, "Trade declined."


def cancel_trade_atomic(data: dict[str, Any], trade_id: str, user_id: str) -> tuple[bool, str]:
    """Cancel a pending trade (initiator only)."""
    ensure_trade_structure(data)
    pending = data["trades"]["pending"]
    trade = pending.get(str(trade_id))
    if not isinstance(trade, dict):
        return False, "trade_not_found"
    if str(trade.get("status", "")) != "pending":
        return False, "trade_not_pending"
    if str(trade.get("initiator_id", "")) != str(user_id):
        return False, "not_your_trade"
    trade["status"] = "cancelled"
    return True, "Trade cancelled."
