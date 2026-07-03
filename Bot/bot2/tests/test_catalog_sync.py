from bot.data.defaults import _sync_catalog_cards, ensure_structure


def test_sync_catalog_cards_updates_seeded_cards_and_preserves_admin_cards() -> None:
    existing = {
        "Vin Jin": {
            "name": "Vin Jin",
            "rarity": "Rare",
            "description": "old",
            "stats": {"strength": 1, "speed": 1, "endurance": 1, "technique": 1, "iq": 1, "battle_iq": 1},
        },
        "Admin Custom": {
            "name": "Admin Custom",
            "rarity": "Common",
            "description": "runtime card",
            "stats": {"strength": 9, "speed": 8, "endurance": 7, "technique": 6, "iq": 5, "battle_iq": 4},
        },
    }
    catalog = {
        "Vin Jin": {
            "name": "Vin Jin",
            "rarity": "Rare",
            "description": "fresh",
            "stats": {"strength": 16, "speed": 22, "endurance": 17, "technique": 24, "iq": 18, "battle_iq": 19},
        }
    }

    synced = _sync_catalog_cards(existing, catalog)

    assert synced["Vin Jin"]["description"] == "fresh"
    assert synced["Vin Jin"]["stats"]["technique"] == 24
    assert synced["Admin Custom"] == existing["Admin Custom"]


def test_sync_catalog_cards_seeds_empty_catalog() -> None:
    catalog = {"Vin Jin": {"name": "Vin Jin", "rarity": "Rare"}}

    assert _sync_catalog_cards({}, catalog) == catalog
    assert _sync_catalog_cards(None, catalog) == catalog


def test_ensure_structure_refreshes_known_cards_without_dropping_runtime_cards() -> None:
    data = {
        "players": {},
        "cards": {
            "Vin Jin": {
                "name": "Vin Jin",
                "rarity": "Rare",
                "description": "old",
                "stats": {"strength": 1, "speed": 1, "endurance": 1, "technique": 1, "iq": 1, "battle_iq": 1},
            },
            "Admin Custom": {
                "name": "Admin Custom",
                "rarity": "Common",
                "description": "runtime card",
                "stats": {"strength": 9, "speed": 8, "endurance": 7, "technique": 6, "iq": 5, "battle_iq": 4},
            },
        },
    }

    normalized = ensure_structure(data)

    assert normalized["cards"]["Vin Jin"]["stats"]["technique"] == 24
    assert normalized["cards"]["Admin Custom"]["description"] == "runtime card"
