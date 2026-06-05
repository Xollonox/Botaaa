"""Pack opening logic."""

from __future__ import annotations

import random
from typing import Any

from bot.utils.cards_logic import RARITIES, build_card_instance

# Guaranteed rarity after N packs without pulling it (highest triggered wins).
PITY_THRESHOLDS: dict[str, dict[str, int]] = {
    "veteran_pack":     {"Infernal": 50, "Mythical": 30, "Legendary": 15},
    "experienced_pack": {"Mythical": 40, "Legendary": 20},
    "intermediate_pack":{"Legendary": 30, "Epic": 15},
    "basic_pack":       {"Epic": 20},
    "amateur_pack":     {"Rare": 15},
}

# Rarities ordered highest-to-lowest for pity priority resolution.
_RARITY_ORDER = ["Abyssal", "Infernal", "Mythical", "Legendary", "Epic", "Rare", "Common"]


def normalize_pack_key(name: str) -> str:
    """Normalize a pack name to a storage key."""
    return str(name).strip().lower().replace(" ", "_")


def ensure_packs_structure(data: dict[str, Any]) -> None:
    """Ensure packs structure exists in data."""
    packs = data.get("packs")
    if not isinstance(packs, dict):
        data["packs"] = {"definitions": {}, "stats": {"total_packs_opened": 0, "total_spent": 0}}
        return
    packs.setdefault("definitions", {})
    if not isinstance(packs.get("definitions"), dict):
        packs["definitions"] = {}
    packs.setdefault("stats", {})
    stats = packs.get("stats", {})
    if not isinstance(stats, dict):
        packs["stats"] = {"total_packs_opened": 0, "total_spent": 0}
    else:
        stats.setdefault("total_packs_opened", 0)
        stats.setdefault("total_spent", 0)


def ensure_player_packs(player: dict[str, Any]) -> None:
    """Ensure packs structure exists on a player dict."""
    packs = player.get("packs")
    if not isinstance(packs, dict):
        player["packs"] = {"opened": 0, "spent": 0}
    else:
        packs.setdefault("opened", 0)
        packs.setdefault("spent", 0)


def get_pack_by_name(data: dict[str, Any], name: str) -> tuple[str | None, dict[str, Any] | None]:
    """Find a pack definition by name. Returns (pack_key, pack_def)."""
    ensure_packs_structure(data)
    key = normalize_pack_key(name)
    definitions = data["packs"]["definitions"]
    if key in definitions and isinstance(definitions[key], dict):
        return key, definitions[key]
    # Try display name match
    name_lower = str(name).strip().lower()
    for pk, pdef in definitions.items():
        if isinstance(pdef, dict) and str(pdef.get("name", "")).lower() == name_lower:
            return pk, pdef
    return None, None


def default_rates() -> dict[str, int]:
    """Return default rarity rates for a new pack."""
    return {
        "Common": 60,
        "Rare": 25,
        "Epic": 10,
        "Legendary": 4,
        "Mythical": 1,
        "Infernal": 0,
        "Abyssal": 0,
    }


def format_rates_table(rates: dict[str, int]) -> str:
    """Format a rates dict as a table string."""
    if not isinstance(rates, dict):
        return "No rates."
    total = sum(int(v) for v in rates.values())
    lines = []
    for rarity in RARITIES:
        val = int(rates.get(rarity, 0))
        if val > 0:
            pct = f"{val / total * 100:.1f}%" if total > 0 else "0%"
            lines.append(f"{rarity}: {val} ({pct})")
    return "\n".join(lines) if lines else "All rates are 0."


def grant_pending_milestone_packs(data: dict[str, Any], user_id: str) -> list[str]:
    """Grant any packs queued in pending_milestone_packs. Returns list of granted pack keys."""
    players = data.get("players", {})
    player = players.get(str(user_id))
    if not isinstance(player, dict):
        return []
    user = player.get("user", {})
    if not isinstance(user, dict):
        return []
    pending = user.get("pending_milestone_packs", [])
    if not pending or not isinstance(pending, list):
        return []

    granted = []
    for pack_key in pending:
        _add_packs_to_inventory(data, str(user_id), pack_key, 1)
        granted.append(pack_key)

    user["pending_milestone_packs"] = []
    return granted


def open_pack_roll(
    data: dict[str, Any],
    user_id: str,
    pack_def: dict[str, Any],
    now: int,
) -> dict[str, Any]:
    """
    Roll and open a pack, adding cards to the user's inventory.

    Returns a result dict with keys: success, reason, instances, cards_data.
    """
    catalog = data.get("cards", {})
    if not isinstance(catalog, dict) or not catalog:
        return {"success": False, "reason": "empty_catalog"}

    rates = pack_def.get("rates", default_rates())
    if not isinstance(rates, dict):
        rates = default_rates()

    cards_per_pack = int(pack_def.get("cards_per_pack", 5))
    cards_per_pack = max(1, min(20, cards_per_pack))

    # Build weighted pool
    pool: list[tuple[str, dict[str, Any]]] = []
    for rarity, weight in rates.items():
        w = int(weight or 0)
        if w <= 0:
            continue
        matching = [
            (name, card)
            for name, card in catalog.items()
            if isinstance(card, dict) and str(card.get("rarity", "")) == rarity
        ]
        pool.extend(matching * w)

    if not pool:
        return {"success": False, "reason": "no_pool"}

    players = data.setdefault("players", {})
    player = players.get(str(user_id))
    if not isinstance(player, dict):
        return {"success": False, "reason": "player_not_found"}

    user = player.get("user", {})
    if not isinstance(user, dict):
        return {"success": False, "reason": "player_data_invalid"}

    inventory = user.setdefault("inventory", [])
    if not isinstance(inventory, list):
        inventory = []
        user["inventory"] = inventory

    pack_key = str(pack_def.get("key", ""))
    thresholds = PITY_THRESHOLDS.get(pack_key, {})
    pity_all: dict[str, dict[str, int]] = user.setdefault("pity", {})
    if not isinstance(pity_all, dict):
        pity_all = {}
        user["pity"] = pity_all
    pity: dict[str, int] = pity_all.setdefault(pack_key, {})
    if not isinstance(pity, dict):
        pity = {}
        pity_all[pack_key] = pity

    instances = []
    cards_data = []
    for _ in range(cards_per_pack):
        # Check pity: find the highest-priority rarity whose counter has hit threshold.
        forced_rarity: str | None = None
        if thresholds:
            for rarity in _RARITY_ORDER:
                threshold = thresholds.get(rarity)
                if threshold is None:
                    continue
                counter_key = f"pulls_since_{rarity.lower()}"
                if pity.get(counter_key, 0) >= threshold:
                    forced_rarity = rarity
                    break

        if forced_rarity is not None:
            forced_pool = [
                (name, card) for name, card in catalog.items()
                if isinstance(card, dict) and str(card.get("rarity", "")) == forced_rarity
            ]
            if forced_pool:
                card_name, card_def = random.choice(forced_pool)
            else:
                card_name, card_def = random.choice(pool)
        else:
            card_name, card_def = random.choice(pool)

        pulled_rarity = str(card_def.get("rarity", ""))

        # Update pity counters: reset pulled rarity, increment all others tracked for this pack.
        for rarity in thresholds:
            counter_key = f"pulls_since_{rarity.lower()}"
            if rarity == pulled_rarity:
                pity[counter_key] = 0
            else:
                pity[counter_key] = pity.get(counter_key, 0) + 1

        instance = build_card_instance(card_def, acquired_at=now)
        inventory.append(instance)
        instances.append(instance)
        cards_data.append(card_def)

    # Update pack stats
    ensure_player_packs(player)
    player["packs"]["opened"] = int(player["packs"].get("opened", 0)) + 1
    player["packs"]["spent"] = int(player["packs"].get("spent", 0)) + int(pack_def.get("price", 0))

    ensure_packs_structure(data)
    data["packs"]["stats"]["total_packs_opened"] = int(data["packs"]["stats"].get("total_packs_opened", 0)) + 1
    data["packs"]["stats"]["total_spent"] = int(data["packs"]["stats"].get("total_spent", 0)) + int(pack_def.get("price", 0))

    return {"success": True, "reason": "ok", "instances": instances, "cards_data": cards_data}
