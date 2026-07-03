import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SEED_CATALOG = ROOT / "Bot" / "bot2" / "bot" / "data" / "cards.json"
LIVE_DATA = ROOT / "Bot" / "bot2" / "lookism_data.json"
STAT_KEYS = ("strength", "speed", "endurance", "technique", "iq", "battle_iq")


def _load_seed_cards() -> dict[str, Any]:
    return json.loads(SEED_CATALOG.read_text(encoding="utf-8"))


def _load_live_cards() -> dict[str, Any] | None:
    if not LIVE_DATA.exists():
        return None
    payload = json.loads(LIVE_DATA.read_text(encoding="utf-8"))
    cards = payload.get("cards", {})
    assert isinstance(cards, dict)
    return cards


def _stat_total(card: dict[str, Any]) -> int:
    stats = card.get("stats", {})
    assert isinstance(stats, dict)
    return sum(int(stats.get(key, 0)) for key in STAT_KEYS)


def test_seed_and_live_catalogs_match_for_cards() -> None:
    seed_cards = _load_seed_cards()
    live_cards = _load_live_cards()

    if live_cards is not None:
        assert live_cards == seed_cards


def test_common_and_rare_cards_stay_inside_rarity_bands() -> None:
    bands = {
        "Common": (0, 50),
        "Rare": (100, 150),
    }

    for name, card in _load_seed_cards().items():
        if not isinstance(card, dict):
            continue
        rarity = str(card.get("rarity", ""))
        if rarity not in bands:
            continue
        low, high = bands[rarity]
        total = _stat_total(card)
        assert low <= total <= high, f"{name} {rarity} total {total} outside {low}-{high}"


def test_card_stats_have_required_keys_and_biq_mirror() -> None:
    for name, card in _load_seed_cards().items():
        if not isinstance(card, dict):
            continue
        stats = card.get("stats", {})
        assert isinstance(stats, dict), f"{name} missing stats"
        for key in STAT_KEYS:
            assert key in stats, f"{name} missing stat {key}"
            assert isinstance(stats[key], int), f"{name} stat {key} must be int"
            assert stats[key] >= 0, f"{name} stat {key} must be non-negative"
        assert stats.get("biq") == stats["battle_iq"], f"{name} biq mirror mismatch"


def test_arc_versions_are_stronger_than_base_versions() -> None:
    cards = _load_seed_cards()

    assert _stat_total(cards["Changyong ji"]) > _stat_total(cards["Changyong Ji"])
    assert _stat_total(cards["Jay Hong Holiday Arc"]) > _stat_total(cards["Jay Hong"])
    assert _stat_total(cards["Vinjin Workers Arc"]) > _stat_total(cards["Vin Jin"])
    assert _stat_total(cards["Magami Kenta 2"]) > _stat_total(cards["Magami Kenta"])
