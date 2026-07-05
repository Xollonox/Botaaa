"""Weapon helpers: build instances, compute buffs, equip/unequip, upgrade."""

from __future__ import annotations

import uuid
from typing import Any

from bot.utils.cards_logic import _FLAT_BONUS, find_catalog_card

_UPGRADE_BASE_COSTS: dict[str, int] = {
    "Common":    500,
    "Rare":      1200,
    "Epic":      3000,
    "Legendary": 6000,
    "Mythical":  9000,
    "Infernal":  14000,
    "Abyssal":   20000,
}


def build_weapon_instance(weapon_def: dict[str, Any], acquired_at: int = 0, stars: int = 0) -> dict[str, Any]:
    return {
        "uid": str(uuid.uuid4()),
        "weapon_name": str(weapon_def.get("name", "")),
        "rarity": str(weapon_def.get("rarity", "Common")),
        "stars": int(stars),
        "locked": False,
        "equipped_to": None,
        "acquired_at": int(acquired_at),
    }


def get_weapon_buffs(weapon_instance: dict[str, Any], weapon_catalog: dict[str, Any]) -> dict[str, int]:
    """Return stat buffs scaled by weapon star level (additive, same as card logic)."""
    weapon_name = str(weapon_instance.get("weapon_name", ""))
    stars = int(weapon_instance.get("stars", 0))
    rarity = str(weapon_instance.get("rarity", "Common"))
    key = weapon_name.lower()
    weapon_def = weapon_catalog.get(key) or weapon_catalog.get(weapon_name)
    if weapon_def is None:
        return {}

    base_buffs = weapon_def.get("stat_buffs", {})
    if not isinstance(base_buffs, dict):
        return {}

    bonus = _FLAT_BONUS.get(rarity, 1) * max(0, min(5, stars))
    result: dict[str, int] = {}
    for k in ("strength", "speed", "endurance", "technique", "iq", "battle_iq"):
        base_val = int(base_buffs.get(k, 0))
        if base_val > 0:
            result[k] = base_val + bonus
        elif base_val < 0:
            result[k] = base_val - bonus
    return result


def _find_weapon_instance(weapon_inv: list[dict[str, Any]], weapon_uid: str) -> tuple[dict[str, Any] | None, int]:
    for idx, w in enumerate(weapon_inv):
        if isinstance(w, dict) and str(w.get("uid", "")) == weapon_uid:
            return w, idx
    return None, -1


def equip_weapon(data: dict[str, Any], user_id: str, weapon_uid: str, card_uid: str) -> tuple[bool, str]:
    """Equip weapon_uid onto card_uid. Returns (ok, message)."""
    player = data.get("players", {}).get(user_id, {})
    if not isinstance(player, dict):
        return False, "Player not found."
    user = player.get("user", {})
    weapon_inv = user.get("weapon_inventory", [])
    card_inv = user.get("inventory", [])

    weapon, _ = _find_weapon_instance(weapon_inv, weapon_uid)
    if weapon is None:
        return False, "Weapon not found."

    if weapon.get("equipped_to"):
        return False, "Weapon is already equipped. Unequip it first."

    card = next((c for c in card_inv if isinstance(c, dict) and str(c.get("uid", "")) == card_uid), None)
    if card is None:
        return False, "Card not found."

    catalog = data.get("cards", {})
    card_def = find_catalog_card(catalog, str(card.get("card_name", "")))
    if card_def is None:
        return False, "Card definition not found."
    if not card_def.get("weapon_user", False):
        return False, f"**{card_def.get('name')}** cannot equip weapons."

    weapons_catalog = data.get("weapons", {})
    weapon_name = str(weapon.get("weapon_name", "")).lower()
    weapon_def = weapons_catalog.get(weapon_name)
    if weapon_def is None:
        return False, "Weapon definition not found."

    compatible = [str(c).lower() for c in weapon_def.get("compatible_cards", [])]
    card_name = str(card_def.get("name", "")).lower()
    if compatible and card_name not in compatible:
        return False, f"This weapon is not compatible with **{card_def.get('name')}**."

    if card.get("weapon_uid"):
        return False, "This card already has a weapon equipped. Unequip it first."

    weapon["equipped_to"] = card_uid
    card["weapon_uid"] = weapon_uid
    return True, str(weapon_def.get("name", ""))


def unequip_weapon(data: dict[str, Any], user_id: str, weapon_uid: str) -> tuple[bool, str]:
    """Unequip weapon_uid from whatever card it's on."""
    player = data.get("players", {}).get(user_id, {})
    if not isinstance(player, dict):
        return False, "Player not found."
    user = player.get("user", {})
    weapon_inv = user.get("weapon_inventory", [])
    card_inv = user.get("inventory", [])

    weapon, _ = _find_weapon_instance(weapon_inv, weapon_uid)
    if weapon is None:
        return False, "Weapon not found."

    card_uid = weapon.get("equipped_to")
    if card_uid:
        card = next((c for c in card_inv if isinstance(c, dict) and str(c.get("uid", "")) == card_uid), None)
        if card is not None:
            card["weapon_uid"] = None

    weapon["equipped_to"] = None
    return True, str(weapon.get("weapon_name", ""))


def upgrade_weapon(data: dict[str, Any], user_id: str, weapon_uid: str) -> tuple[str, int, int]:
    """Upgrade weapon by 1 star. Returns (status, new_stars, balance)."""
    player = data.get("players", {}).get(user_id, {})
    if not isinstance(player, dict):
        return "not_found", 0, 0
    user = player.get("user", {})
    weapon_inv = user.get("weapon_inventory", [])

    weapon, w_idx = _find_weapon_instance(weapon_inv, weapon_uid)
    if weapon is None:
        return "not_found", 0, 0

    if weapon.get("equipped_to"):
        return "equipped", 0, 0

    stars = int(weapon.get("stars", 0))
    if stars >= 5:
        return "maxed", stars, int(user.get("balance", 0))

    rarity = str(weapon.get("rarity", "Common"))
    base_cost = _UPGRADE_BASE_COSTS.get(rarity, 500)
    cost = int(round(base_cost * (1.6 ** stars)))
    balance = int(user.get("balance", user.get("coins", 0)))

    if balance < cost:
        return "not_enough", stars, balance

    weapon_name = str(weapon.get("weapon_name", "")).lower()
    dup_idx = next(
        (i for i, w in enumerate(weapon_inv)
         if isinstance(w, dict)
         and str(w.get("weapon_name", "")).lower() == weapon_name
         and str(w.get("uid", "")) != weapon_uid
         and not bool(w.get("locked", False))
         and not w.get("equipped_to")),
        -1,
    )
    if dup_idx < 0:
        return "need_duplicate", stars, balance

    user["balance"] = balance - cost
    if "coins" in user:
        user["coins"] = user["balance"]
    weapon_inv.pop(dup_idx)
    weapon["stars"] = stars + 1
    return "ok", stars + 1, int(user.get("balance", 0))
