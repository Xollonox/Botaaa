"""Squad management helpers."""

from __future__ import annotations

from typing import Any

from bot.utils.cards_logic import compute_power, compute_scaled_stats, find_catalog_card


def get_player(data: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    """Return the player dict for *user_id*, or None if not found."""
    players = data.get("players", {})
    return players.get(str(user_id)) if isinstance(players, dict) else None


def get_inventory(player: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the player's inventory list, or []."""
    user = player.get("user", {}) if isinstance(player, dict) else {}
    inv = user.get("inventory", []) if isinstance(user, dict) else []
    return inv if isinstance(inv, list) else []


def get_squad(player: dict[str, Any]) -> dict[str, Any]:
    """Return the squad dict from a player, ensuring correct structure."""
    if not isinstance(player, dict):
        return {"active": [], "backup": [], "supervisor": ""}
    squad = player.get("squad", {})
    if not isinstance(squad, dict):
        squad = {}
        player["squad"] = squad
    squad.setdefault("active", [])
    squad.setdefault("backup", [])
    squad.setdefault("supervisor", "")
    if not isinstance(squad["active"], list):
        squad["active"] = []
    if not isinstance(squad["backup"], list):
        squad["backup"] = []
    # Auto-cleanup empty/invalid UIDs on every read
    for key in ("active", "backup"):
        squad[key] = [str(v) for v in squad[key] if v and str(v).strip()]
    return squad


def uid_in_squad(squad: dict[str, Any], uid: str) -> bool:
    """Return True if *uid* is in the active or backup squad."""
    for slot in ("active", "backup"):
        if uid in (squad.get(slot) or []):
            return True
    return False


def remove_uid_from_squad(squad: dict[str, Any], uid: str) -> bool:
    """Remove *uid* from active and backup if present. Returns True if removed."""
    removed = False
    for slot in ("active", "backup"):
        lst = squad.get(slot, [])
        if isinstance(lst, list) and uid in lst:
            lst.remove(uid)
            removed = True
    supervisor = squad.get("supervisor", "")
    if str(supervisor) == str(uid):
        squad["supervisor"] = ""
        removed = True
    return removed


def resolve_instance_and_def(
    data: dict[str, Any], player: dict[str, Any], uid: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (instance, card_def) for the given UID, or (None, None)."""
    inventory = get_inventory(player)
    instance = next(
        (item for item in inventory if isinstance(item, dict) and str(item.get("uid", "")) == uid),
        None,
    )
    if instance is None:
        return None, None
    card_name = str(instance.get("card_name", ""))
    catalog = data.get("cards", {})
    card_def = find_catalog_card(catalog, card_name) if isinstance(catalog, dict) else None
    return instance, card_def if isinstance(card_def, dict) else None


def compute_squad_power(
    data: dict[str, Any], player: dict[str, Any], slot: str = "active"
) -> int:
    """Compute total scaled power for the given squad slot."""
    squad = get_squad(player)
    uid_list = squad.get(slot, [])
    if not isinstance(uid_list, list):
        return 0

    inventory = get_inventory(player)
    catalog = data.get("cards", {}) or {}
    total = 0
    for uid in uid_list:
        instance = next(
            (item for item in inventory if isinstance(item, dict) and str(item.get("uid", "")) == uid),
            None,
        )
        if instance is None:
            continue
        card_name = str(instance.get("card_name", ""))
        card_def = find_catalog_card(catalog, card_name)
        if not isinstance(card_def, dict):
            continue
        stars = int(instance.get("stars", 0))
        scaled = compute_scaled_stats(card_def, stars)
        total += compute_power(scaled)
    return total


def format_instance_line(instance: dict[str, Any], data: dict[str, Any]) -> str:
    """Format an inventory instance as a display line."""
    from bot.utils.ui import e
    uid_short = str(instance.get("uid", ""))[:8]
    card_name = str(instance.get("card_name", "Unknown"))
    rarity = str(instance.get("rarity", "Common"))
    stars = int(instance.get("stars", 0))
    locked = e("lock", data) if instance.get("locked") else ""
    fav = e("favorite", data) if instance.get("favourite") else ""
    markers = " ".join(x for x in [locked, fav] if x)
    suffix = f" {markers}" if markers else ""
    return f"{e('card', data)} {card_name} • {rarity} • {e('star', data)}x{stars} • UID:{uid_short}{suffix}"
