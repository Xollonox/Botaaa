"""Attack catalog management logic."""

from __future__ import annotations

from typing import Any

ATTACK_TYPES = ["normal", "special", "ultimate", "unique_skill", "unique_path"]

DEFENSE_TYPES = ["block", "dodge", "parry", "revert", "tank"]

DEFAULT_USES: dict[str, int] = {
    "normal": 999,
    "special": 5,
    "ultimate": 2,
    "unique_skill": 1,
    "unique_path": 1,
}


def ensure_attacks_structure(data: dict[str, Any]) -> None:
    """Ensure attacks structure exists in data."""
    attacks = data.get("attacks")
    if not isinstance(attacks, dict):
        data["attacks"] = {"catalog": {}}
    else:
        attacks.setdefault("catalog", {})
        if not isinstance(attacks.get("catalog"), dict):
            attacks["catalog"] = {}


def validate_attack_type(attack_type: str) -> bool:
    """Return True if *attack_type* is valid."""
    return str(attack_type).lower() in ATTACK_TYPES


def default_uses_for_type(attack_type: str) -> int:
    """Return the default use count for an attack type."""
    return DEFAULT_USES.get(str(attack_type).lower(), 999)


def attack_key(name: str) -> str:
    """Normalize an attack name to a storage key."""
    return str(name).strip().lower().replace(" ", "_")


def create_attack_entry(
    name: str,
    attack_type: str,
    description: str = "",
    power: int = 0,
    uses: int | None = None,
) -> dict[str, Any]:
    """Create an attack catalog entry."""
    key = attack_key(name)
    actual_uses = uses if uses is not None else default_uses_for_type(attack_type)
    return {
        "key": key,
        "name": str(name).strip(),
        "type": str(attack_type).lower(),
        "description": str(description).strip(),
        "power": int(power),
        "uses": int(actual_uses),
    }


def validate_attack_payload(entry: dict[str, Any]) -> tuple[bool, str]:
    """Validate an attack entry. Returns (ok, message)."""
    name = str(entry.get("name", "")).strip()
    if not name:
        return False, "Attack name cannot be empty."
    attack_type = str(entry.get("type", "")).lower()
    if attack_type not in ATTACK_TYPES:
        return False, f"Invalid attack type '{attack_type}'. Must be one of {ATTACK_TYPES}."
    power = entry.get("power", 0)
    if not isinstance(power, int) or power < 0:
        return False, "Power must be a non-negative integer."
    return True, "OK"


def list_attacks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of all attack catalog entries."""
    ensure_attacks_structure(data)
    catalog = data["attacks"]["catalog"]
    return [entry for entry in catalog.values() if isinstance(entry, dict)]


def card_attack_keys(card: dict[str, Any]) -> list[str]:
    """Return the list of attack keys assigned to a card."""
    attacks = card.get("attacks", [])
    return list(attacks) if isinstance(attacks, list) else []


def assigned_cards_for_attack(data: dict[str, Any], attack_key_str: str) -> list[str]:
    """Return list of card names that have *attack_key_str* assigned."""
    catalog = data.get("cards", {})
    if not isinstance(catalog, dict):
        return []
    assigned = []
    for card_name, card in catalog.items():
        if not isinstance(card, dict):
            continue
        if attack_key_str in card_attack_keys(card):
            assigned.append(str(card_name))
    return assigned


def remove_attack_from_all_cards(data: dict[str, Any], attack_key_str: str) -> int:
    """Remove *attack_key_str* from all cards. Returns count of affected cards."""
    catalog = data.get("cards", {})
    if not isinstance(catalog, dict):
        return 0
    count = 0
    for card in catalog.values():
        if not isinstance(card, dict):
            continue
        attacks = card.get("attacks", [])
        if isinstance(attacks, list) and attack_key_str in attacks:
            attacks.remove(attack_key_str)
            count += 1
    return count


def rename_attack_key_everywhere(data: dict[str, Any], old_key: str, new_key: str) -> int:
    """Rename an attack key in the catalog and all card assignments. Returns affected count."""
    ensure_attacks_structure(data)
    attack_catalog = data["attacks"]["catalog"]

    # Rename in catalog
    entry = attack_catalog.pop(old_key, None)
    if isinstance(entry, dict):
        entry["key"] = new_key
        attack_catalog[new_key] = entry

    # Rename in card assignments
    count = 0
    cards = data.get("cards", {})
    if isinstance(cards, dict):
        for card in cards.values():
            if not isinstance(card, dict):
                continue
            attacks = card.get("attacks", [])
            if isinstance(attacks, list) and old_key in attacks:
                idx = attacks.index(old_key)
                attacks[idx] = new_key
                count += 1
    return count
