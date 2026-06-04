"""Inventory API helpers for card instance management."""

from __future__ import annotations

from typing import Any

from bot.utils.cards_logic import build_card_instance


def add_card_instance_from_def(
    user: dict[str, Any],
    card_def: dict[str, Any],
    acquired_at: int = 0,
    stars: int = 0,
) -> dict[str, Any]:
    """Add a new card instance to *user* inventory and return the instance."""
    instance = build_card_instance(card_def, acquired_at=acquired_at, stars=stars)
    inventory = user.setdefault("inventory", [])
    if not isinstance(inventory, list):
        inventory = []
        user["inventory"] = inventory
    inventory.append(instance)
    return instance


def find_card_instance(
    user: dict[str, Any], query: str
) -> tuple[dict[str, Any] | None, int | None]:
    """Find an owned card instance in *user* inventory by UID or name."""
    from bot.utils.cards_logic import find_owned_instance
    inventory = user.get("inventory", [])
    if not isinstance(inventory, list):
        return None, None
    return find_owned_instance(inventory, query)


def remove_card_instance(user: dict[str, Any], uid: str) -> bool:
    """Remove the card instance with *uid* from *user* inventory. Returns True if removed."""
    inventory = user.get("inventory", [])
    if not isinstance(inventory, list):
        return False
    for idx, item in enumerate(inventory):
        if isinstance(item, dict) and str(item.get("uid", "")) == uid:
            inventory.pop(idx)
            return True
    return False


def is_locked(instance: dict[str, Any]) -> bool:
    """Return True if the card instance is locked (squad or market locked)."""
    return bool(instance.get("locked", False)) or bool(instance.get("market_locked", False)) or bool(instance.get("squad_locked", False))


def lock_card_instance(user: dict[str, Any], uid: str) -> bool:
    """Lock the card instance with *uid*. Returns True if found and locked."""
    inventory = user.get("inventory", [])
    if not isinstance(inventory, list):
        return False
    for item in inventory:
        if isinstance(item, dict) and str(item.get("uid", "")) == uid:
            item["locked"] = True
            return True
    return False


def unlock_card_instance(user: dict[str, Any], uid: str) -> bool:
    """Unlock the card instance with *uid*. Returns True if found and unlocked."""
    inventory = user.get("inventory", [])
    if not isinstance(inventory, list):
        return False
    for item in inventory:
        if isinstance(item, dict) and str(item.get("uid", "")) == uid:
            item["locked"] = False
            return True
    return False
