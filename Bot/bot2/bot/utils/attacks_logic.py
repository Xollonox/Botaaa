"""Attack catalog management logic."""

from __future__ import annotations

from typing import Any

from bot.utils.cards_logic import find_catalog_card

ATTACK_TYPES = ["normal", "special", "ultimate", "unique_skill", "unique_path"]

# Battle normalization still accepts legacy revert; the owner catalog UI does not
# offer it for new assignment setup.
DEFENSE_TYPES = ["block", "dodge", "parry", "revert", "tank"]
OWNER_DEFENSE_TYPES = ["parry", "dodge", "tank", "block"]
CATALOG_ATTACK_TYPES = ATTACK_TYPES + OWNER_DEFENSE_TYPES
ASSIGNMENT_LIMITS: dict[str, int] = {
    "normal": 5,
    "special": 4,
    "ultimate": 1,
    "unique_skill": 2,
    "unique_path": 1,
}
DEFENSE_ASSIGNMENT_LIMIT = 4

DEFAULT_USES: dict[str, int] = {
    "normal": -1,
    "special": 5,
    "ultimate": 1,
    "unique_skill": 1,
    "unique_path": 1,
    "parry": 1,
    "dodge": 1,
    "tank": 1,
    "block": 1,
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
    return str(attack_type).lower() in CATALOG_ATTACK_TYPES


def default_uses_for_type(attack_type: str) -> int:
    """Return the default use count for an attack type."""
    return DEFAULT_USES.get(str(attack_type).lower(), 999)


def attack_key(name: str) -> str:
    """Normalize an attack name to a storage key."""
    return str(name).strip().lower().replace(" ", "_")


def create_attack_entry(
    name: str,
    attack_type: str,
    power: int = 0,
    description: str = "",
    uses_per_battle: int | None = None,
) -> dict[str, Any]:
    """Create an attack catalog entry."""
    key = attack_key(name)
    actual_uses = uses_per_battle if uses_per_battle is not None else default_uses_for_type(attack_type)
    return {
        "key": key,
        "name": str(name).strip(),
        "type": str(attack_type).lower(),
        "description": str(description).strip(),
        "power": int(power),
        "uses_per_battle": int(actual_uses),
    }


def validate_attack_payload(entry: dict[str, Any]) -> tuple[bool, str]:
    """Validate an attack entry. Returns (ok, message)."""
    name = str(entry.get("name", "")).strip()
    if not name:
        return False, "Attack name cannot be empty."
    attack_type = str(entry.get("type", "")).lower()
    if attack_type not in CATALOG_ATTACK_TYPES:
        return False, f"Invalid attack type '{attack_type}'. Must be one of {CATALOG_ATTACK_TYPES}."
    power = entry.get("power", 0)
    if not isinstance(power, int) or power < 0:
        return False, "Power must be a non-negative integer."
    uses = entry.get("uses_per_battle", default_uses_for_type(attack_type))
    if not isinstance(uses, int) or uses < -1:
        return False, "Uses per battle must be -1 or a non-negative integer."
    return True, "OK"


def list_attacks(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return sorted attack catalog key/entry pairs."""
    ensure_attacks_structure(data)
    catalog = data["attacks"]["catalog"]
    return sorted(
        [(str(key), entry) for key, entry in catalog.items() if isinstance(entry, dict)],
        key=lambda pair: str(pair[1].get("name", pair[0])).lower(),
    )


def card_attack_keys(data_or_card: dict[str, Any], card_name: str | None = None) -> list[str]:
    """Return the list of attack keys assigned to a card."""
    if card_name is not None:
        cards = data_or_card.get("cards", {}) if isinstance(data_or_card, dict) else {}
        if not isinstance(cards, dict):
            return []
        card = find_catalog_card(cards, card_name)
        if not isinstance(card, dict):
            return []
    else:
        card = data_or_card
    attacks = card.get("attacks", [])
    return list(attacks) if isinstance(attacks, list) else []


def _card_by_name(data: dict[str, Any], card_name: str) -> tuple[str | None, dict[str, Any] | None]:
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        return None, None
    if card_name in cards and isinstance(cards[card_name], dict):
        return card_name, cards[card_name]
    target = str(card_name).strip().lower()
    for key, card in cards.items():
        if isinstance(card, dict) and str(card.get("name", key)).strip().lower() == target:
            return str(key), card
    return None, None


def add_attack_to_catalog(data: dict[str, Any], entry: dict[str, Any]) -> tuple[bool, str]:
    """Add a validated attack entry to the catalog."""
    ensure_attacks_structure(data)
    ok, msg = validate_attack_payload(entry)
    if not ok:
        return False, msg
    key = attack_key(str(entry.get("name", "")))
    catalog = data["attacks"]["catalog"]
    if key in catalog:
        return False, "Attack already exists."
    entry["key"] = key
    catalog[key] = entry
    return True, key


def edit_attack_in_catalog(data: dict[str, Any], attack_name: str, updates: dict[str, Any]) -> tuple[bool, str]:
    """Apply non-None updates to an attack catalog entry."""
    ensure_attacks_structure(data)
    catalog = data["attacks"]["catalog"]
    key = attack_name if attack_name in catalog else attack_key(attack_name)
    if key not in catalog or not isinstance(catalog[key], dict):
        return False, "Attack not found."
    entry = catalog[key]

    if updates.get("name") is not None:
        new_name = str(updates["name"]).strip()
        if not new_name:
            return False, "Attack name cannot be empty."
        new_key = attack_key(new_name)
        if new_key != key and new_key in catalog:
            return False, "Another attack already has that name."
        entry["name"] = new_name
        entry["key"] = new_key
    else:
        new_key = key

    for field in ("description",):
        if updates.get(field) is not None:
            entry[field] = str(updates[field]).strip()
    if updates.get("type") is not None:
        attack_type = str(updates["type"]).lower()
        if not validate_attack_type(attack_type):
            return False, "Invalid attack type."
        entry["type"] = attack_type
    if updates.get("power") is not None:
        entry["power"] = int(updates["power"])
    if updates.get("uses_per_battle") is not None:
        entry["uses_per_battle"] = int(updates["uses_per_battle"])

    ok, msg = validate_attack_payload(entry)
    if not ok:
        return False, msg
    if new_key != key:
        catalog[new_key] = entry
        del catalog[key]
        rename_attack_key_everywhere(data, key, new_key)
    return True, new_key


def assignment_limit_status(data: dict[str, Any], card: dict[str, Any], attack_type: str) -> tuple[bool, str]:
    """Return whether a card may receive another attack of this type."""
    ensure_attacks_structure(data)
    catalog = data["attacks"]["catalog"]
    attack_type = str(attack_type).lower()
    assigned = card.get("attacks", [])
    if not isinstance(assigned, list):
        assigned = []
    counts: dict[str, int] = {}
    defense_count = 0
    for key in assigned:
        entry = catalog.get(str(key))
        typ = str(entry.get("type", "")).lower() if isinstance(entry, dict) else ""
        if typ in OWNER_DEFENSE_TYPES:
            defense_count += 1
        else:
            counts[typ] = counts.get(typ, 0) + 1

    if attack_type in OWNER_DEFENSE_TYPES:
        if defense_count >= DEFENSE_ASSIGNMENT_LIMIT:
            return False, f"Defense assignment limit reached ({DEFENSE_ASSIGNMENT_LIMIT})."
        return True, "OK"
    limit = ASSIGNMENT_LIMITS.get(attack_type)
    if limit is not None and counts.get(attack_type, 0) >= limit:
        return False, f"{attack_type} assignment limit reached ({limit})."
    return True, "OK"


def assign_attack_to_card(data: dict[str, Any], card_name: str, attack_name: str) -> tuple[bool, str]:
    """Assign a catalog attack key to a card, enforcing type limits."""
    ensure_attacks_structure(data)
    catalog = data["attacks"]["catalog"]
    attack_id = attack_name if attack_name in catalog else attack_key(attack_name)
    entry = catalog.get(attack_id)
    if not isinstance(entry, dict):
        return False, "Attack not found."
    _, card = _card_by_name(data, card_name)
    if not isinstance(card, dict):
        return False, "Card not found."
    attacks = card.setdefault("attacks", [])
    if not isinstance(attacks, list):
        attacks = []
        card["attacks"] = attacks
    if attack_id in attacks:
        return True, "Attack already assigned."
    ok, msg = assignment_limit_status(data, card, str(entry.get("type", "")))
    if not ok:
        return False, msg
    attacks.append(attack_id)
    return True, "Attack assigned."


def remove_attack_from_card(data: dict[str, Any], card_name: str, attack_name: str) -> tuple[bool, str]:
    """Remove one attack assignment from a card."""
    _, card = _card_by_name(data, card_name)
    if not isinstance(card, dict):
        return False, "Card not found."
    attack_id = attack_name
    attacks = card.get("attacks", [])
    if not isinstance(attacks, list) or attack_id not in attacks:
        return False, "Assignment not found."
    card["attacks"] = [str(key) for key in attacks if str(key) != attack_id]
    return True, "Assignment removed."


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
