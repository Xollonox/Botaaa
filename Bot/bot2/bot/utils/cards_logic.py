"""Card catalog logic: definitions, power, stats, and instance helpers."""

from __future__ import annotations

import random
import uuid
from typing import Any

RARITIES: list[str] = ["Common", "Rare", "Epic", "Legendary", "Mythical", "Infernal", "Abyssal"]

MASTERY_VALUES: list[str] = ["Strength", "Speed", "Endurance", "Technique"]

def get_star_multiplier(stars: int) -> float:
    """Return linear star multiplier clamped to 0..5 (0★=1.00, 5★=1.30)."""
    s = max(0, min(5, int(stars or 0)))
    return 1.0 + s * 0.06

_RARITY_RANK_MAP: dict[str, int] = {r: i for i, r in enumerate(RARITIES)}


def rarity_rank(rarity: str) -> int:
    """Return a numeric rank for *rarity* (higher = rarer)."""
    return _RARITY_RANK_MAP.get(rarity, 0)


def compute_power(stats: dict[str, int]) -> int:
    """Compute aggregate card power from a stats dict."""
    return sum(int(stats.get(k, 0)) for k in ("strength", "speed", "endurance", "technique", "iq", "battle_iq"))


_SCALED_CACHE: dict[tuple[frozenset, int], dict[str, int]] = {}

def compute_scaled_stats(card: dict[str, Any], stars: int) -> dict[str, int]:
    """Return a new stats dict scaled by the star multiplier.

    Results are cached by (stats_tuple, stars) to avoid recomputation
    on repeated lookups (collection view, squad display, etc).
    Clear with ``clear_scaled_cache()`` after admin card edits.
    """
    base = card.get("stats", {})
    if not isinstance(base, dict):
        base = {}
    key = (frozenset(base.items()), int(stars))
    cached = _SCALED_CACHE.get(key)
    if cached is not None:
        return cached
    mult = get_star_multiplier(stars)
    result = {
        "strength": int(int(base.get("strength", 0)) * mult),
        "speed": int(int(base.get("speed", 0)) * mult),
        "endurance": int(int(base.get("endurance", 0)) * mult),
        "technique": int(int(base.get("technique", 0)) * mult),
        "iq": int(int(base.get("iq", 0)) * mult),
        "battle_iq": int(int(base.get("battle_iq", base.get("biq", 0))) * mult),
    }
    _SCALED_CACHE[key] = result
    return result


def clear_scaled_cache() -> None:
    """Clear the internal scaled-stats cache. Call after admin edits a card."""
    _SCALED_CACHE.clear()


def build_card_def(
    *,
    name: str,
    title: str = "",
    description: str = "",
    rarity: str = "Common",
    strength: int = 0,
    speed: int = 0,
    endurance: int = 0,
    technique: int = 0,
    iq: int = 0,
    battle_iq: int = 0,
    mastery_list: list[str] | None = None,
    unique_skill: str | None = None,
    unique_skill_description: str | None = None,
    unique_path: str | None = None,
    unique_path_description: str | None = None,
    image_url: str | None = None,
    emoji: str | None = None,
) -> dict[str, Any]:
    """Build a card catalog definition dict."""
    stats = {
        "strength": int(strength),
        "speed": int(speed),
        "endurance": int(endurance),
        "technique": int(technique),
        "iq": int(iq),
        "battle_iq": int(battle_iq),
        "biq": int(battle_iq),
    }
    card: dict[str, Any] = {
        "name": str(name).strip(),
        "title": str(title).strip(),
        "description": str(description).strip(),
        "rarity": str(rarity),
        "stats": stats,
        "power": compute_power(stats),
        "mastery": normalize_mastery_list(mastery_list or []),
        "attacks": [],
        "image_url": str(image_url).strip() if image_url else "",
    }
    if emoji:
        card["emoji"] = str(emoji).strip()
    if unique_skill:
        card["unique_skill"] = str(unique_skill).strip()
        card["unique_skill_description"] = str(unique_skill_description or "").strip()
    if unique_path:
        card["unique_path"] = str(unique_path).strip()
        card["unique_path_description"] = str(unique_path_description or "").strip()
    return card


def normalize_mastery_list(values: list[str] | tuple[str, ...] | set[str] | Any) -> list[str]:
    """Return canonical mastery values in display order."""
    if isinstance(values, dict):
        raw_values = [values.get("type", "")]
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    elif values:
        raw_values = [values]
    else:
        raw_values = []

    wanted = {str(v).strip().lower() for v in raw_values if str(v).strip()}
    return [m for m in MASTERY_VALUES if m.lower() in wanted]


def mastery_list_from_flags(
    *,
    strength: bool = False,
    speed: bool = False,
    endurance: bool = False,
    technique: bool = False,
) -> list[str]:
    """Build a mastery list from slash-command boolean fields."""
    return [
        label
        for label, enabled in (
            ("Strength", strength),
            ("Speed", speed),
            ("Endurance", endurance),
            ("Technique", technique),
        )
        if bool(enabled)
    ]


def find_catalog_key(catalog: dict[str, Any], query: str) -> str | None:
    """Find the storage key for a catalog card by key or case-insensitive card name."""
    if not isinstance(catalog, dict):
        return None
    q = str(query).strip()
    if q in catalog and isinstance(catalog[q], dict):
        return q
    q_lower = q.lower()
    for key, card in catalog.items():
        if not isinstance(card, dict):
            continue
        if str(card.get("name", key)).strip().lower() == q_lower:
            return str(key)
    return None


def add_card_def(data: dict[str, Any], card: dict[str, Any]) -> tuple[bool, str]:
    """Add a card definition to catalog data."""
    cards = data.setdefault("cards", {})
    if not isinstance(cards, dict):
        data["cards"] = {}
        cards = data["cards"]
    ok, msg = validate_card_def(card)
    if not ok:
        return False, msg
    name = str(card.get("name", "")).strip()
    if find_catalog_key(cards, name) is not None:
        return False, "Card already exists."
    cards[name] = card
    clear_scaled_cache()
    return True, name


def edit_card_def(data: dict[str, Any], card_name: str, updates: dict[str, Any]) -> tuple[bool, str]:
    """Apply non-None field updates to an existing catalog card."""
    cards = data.setdefault("cards", {})
    if not isinstance(cards, dict):
        return False, "Card catalog is unavailable."
    key = find_catalog_key(cards, card_name)
    if key is None:
        return False, "Card not found."
    card = cards.get(key)
    if not isinstance(card, dict):
        return False, "Card not found."

    if "name" in updates and updates["name"] is not None:
        new_name = str(updates["name"]).strip()
        if not new_name:
            return False, "Card name cannot be empty."
        existing = find_catalog_key(cards, new_name)
        if existing is not None and existing != key:
            return False, "Another card already has that name."
        card["name"] = new_name

    for field in ("title", "description", "image_url", "rarity", "unique_path", "unique_path_description", "unique_skill", "unique_skill_description", "emoji"):
        if field in updates and updates[field] is not None:
            card[field] = str(updates[field]).strip()

    stat_updates = updates.get("stats")
    if isinstance(stat_updates, dict):
        stats = card.setdefault("stats", {})
        if not isinstance(stats, dict):
            stats = {}
            card["stats"] = stats
        for field, value in stat_updates.items():
            if value is None:
                continue
            key_name = "battle_iq" if field == "biq" else field
            stats[key_name] = int(value)
            if field == "biq":
                stats["biq"] = int(value)

    mastery = updates.get("mastery")
    if mastery is not None:
        card["mastery"] = normalize_mastery_list(mastery)

    ok, msg = validate_card_def(card)
    if not ok:
        return False, msg

    new_key = str(card.get("name", key)).strip()
    if new_key != key:
        cards[new_key] = card
        del cards[key]
    clear_scaled_cache()
    return True, new_key


def delete_card_def(data: dict[str, Any], card_name: str, confirm: str) -> tuple[bool, str]:
    """Delete a catalog card when confirm is exactly DELETE."""
    if str(confirm).strip() != "DELETE":
        return False, "Confirmation must be DELETE."
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        return False, "Card catalog is unavailable."
    key = find_catalog_key(cards, card_name)
    if key is None:
        return False, "Card not found."
    del cards[key]
    clear_scaled_cache()
    return True, key


def validate_card_def(card: dict[str, Any]) -> tuple[bool, str]:
    """Validate a card definition dict. Returns (ok, message)."""
    name = str(card.get("name", "")).strip()
    if not name:
        return False, "Card name cannot be empty."
    rarity = str(card.get("rarity", ""))
    if rarity not in RARITIES:
        return False, f"Invalid rarity '{rarity}'. Must be one of {RARITIES}."
    stats = card.get("stats", {})
    if not isinstance(stats, dict):
        return False, "Stats must be a dict."
    for stat in ("strength", "speed", "endurance", "technique", "iq", "battle_iq"):
        val = stats.get(stat, 0)
        if not isinstance(val, int) or val < 0:
            return False, f"Stat '{stat}' must be a non-negative integer."
    if "mastery" in card:
        current_mastery = card.get("mastery", [])
        normalized_mastery = normalize_mastery_list(current_mastery)
        if not isinstance(current_mastery, list) or current_mastery != normalized_mastery:
            card["mastery"] = normalized_mastery
    return True, "OK"


def find_catalog_card(catalog: dict[str, Any], query: str) -> dict[str, Any] | None:
    """Find a card in *catalog* by exact name or case-insensitive name match."""
    if not isinstance(catalog, dict):
        return None
    q = str(query).strip()
    # Exact key match
    if q in catalog and isinstance(catalog[q], dict):
        return catalog[q]
    # Case-insensitive name match
    q_lower = q.lower()
    for card in catalog.values():
        if not isinstance(card, dict):
            continue
        if str(card.get("name", "")).lower() == q_lower:
            return card
    return None


def find_owned_instance(
    inventory: list[dict[str, Any]], query: str
) -> tuple[dict[str, Any] | None, int | None]:
    """
    Find an owned card instance in *inventory* by UID prefix or card name.

    Returns (instance, index) or (None, None).
    """
    if not isinstance(inventory, list):
        return None, None
    q = str(query).strip()
    q_lower = q.lower()
    # Try UID prefix match first
    for idx, item in enumerate(inventory):
        if not isinstance(item, dict):
            continue
        if str(item.get("uid", "")).startswith(q):
            return item, idx
    # Try card name match
    for idx, item in enumerate(inventory):
        if not isinstance(item, dict):
            continue
        if q_lower in str(item.get("card_name", "")).lower():
            return item, idx
    return None, None


def build_card_instance(
    card_def: dict[str, Any],
    acquired_at: int = 0,
    stars: int = 0,
) -> dict[str, Any]:
    """Create an owned card instance from a catalog definition."""
    return {
        "uid": str(uuid.uuid4()),
        "card_name": str(card_def.get("name", "")),
        "rarity": str(card_def.get("rarity", "Common")),
        "stars": int(stars),
        "locked": False,
        "market_locked": False,
        "squad_locked": False,
        "favourite": False,
        "acquired_at": int(acquired_at),
    }


def grant_random_bonus_card(
    data: dict[str, Any],
    user_id: str,
    reward_type: str,
    now: int,
) -> dict[str, Any]:
    """
    Try to grant a random bonus card from the reward_card_bonus config.

    Returns a result dict with keys: granted, reason, instance, card.
    """
    catalog = data.get("cards", {})
    if not isinstance(catalog, dict) or not catalog:
        return {"granted": False, "reason": "empty_catalog"}

    bonus_cfg = (
        data.get("config", {})
        .get("reward_card_bonus", {})
        .get(reward_type, {})
    )
    if not isinstance(bonus_cfg, dict) or not bool(bonus_cfg.get("enabled", False)):
        return {"granted": False, "reason": "disabled"}

    rates = bonus_cfg.get("rates", {})
    if not isinstance(rates, dict) or not rates:
        return {"granted": False, "reason": "no_rates"}

    # Build pool weighted by rates
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
        return {"granted": False, "reason": "no_pool"}

    card_name, card_def = random.choice(pool)
    instance = build_card_instance(card_def, acquired_at=now)

    players = data.setdefault("players", {})
    player = players.get(str(user_id))
    if not isinstance(player, dict):
        return {"granted": False, "reason": "player_not_found"}

    user = player.get("user", {})
    if not isinstance(user, dict):
        return {"granted": False, "reason": "player_data_invalid"}

    inventory = user.setdefault("inventory", [])
    if not isinstance(inventory, list):
        inventory = []
        user["inventory"] = inventory
    inventory.append(instance)

    return {"granted": True, "reason": "ok", "instance": instance, "card": card_def}
