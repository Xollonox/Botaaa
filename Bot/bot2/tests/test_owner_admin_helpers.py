"""Tests for grouped owner card and attack admin helpers."""

from __future__ import annotations

from bot.utils.attacks_logic import (
    add_attack_to_catalog,
    assign_attack_to_card,
    create_attack_entry,
    remove_attack_from_all_cards,
)
from bot.utils.cards_logic import (
    add_card_def,
    build_card_def,
    delete_card_def,
    edit_card_def,
    mastery_list_from_flags,
)


def _card(name: str = "Daniel") -> dict:
    return build_card_def(
        name=name,
        rarity="Legendary",
        strength=10,
        speed=20,
        endurance=30,
        technique=40,
        iq=50,
        battle_iq=60,
        mastery_list=["Strength"],
    )


def test_card_add_edit_delete_helpers() -> None:
    data: dict = {"cards": {}}
    ok, key = add_card_def(data, _card())
    assert ok
    assert key == "Daniel"
    assert data["cards"]["Daniel"]["stats"]["battle_iq"] == 60

    ok, key = edit_card_def(
        data,
        "Daniel",
        {
            "name": "Park Daniel",
            "description": "Public bio",
            "stats": {"speed": 25, "biq": 65},
            "mastery": ["Speed", "Technique"],
        },
    )
    assert ok
    assert key == "Park Daniel"
    assert "Daniel" not in data["cards"]
    edited = data["cards"]["Park Daniel"]
    assert edited["description"] == "Public bio"
    assert edited["stats"]["speed"] == 25
    assert edited["stats"]["battle_iq"] == 65
    assert edited["mastery"] == ["Speed", "Technique"]

    ok, msg = delete_card_def(data, "Park Daniel", "no")
    assert not ok
    assert msg == "Confirmation must be DELETE."

    ok, key = delete_card_def(data, "Park Daniel", "DELETE")
    assert ok
    assert key == "Park Daniel"
    assert data["cards"] == {}


def test_mastery_list_from_flags_keeps_only_enabled_masteries() -> None:
    assert mastery_list_from_flags(
        strength=True,
        speed=False,
        endurance=True,
        technique=False,
    ) == ["Strength", "Endurance"]


def test_attack_assignment_limits_by_type_and_defense_total() -> None:
    data = {"cards": {"Daniel": _card()}, "attacks": {"catalog": {}}}
    for idx in range(5):
        add_attack_to_catalog(data, create_attack_entry(f"Normal {idx}", "normal", 1, ""))
        ok, _ = assign_attack_to_card(data, "Daniel", f"normal_{idx}")
        assert ok
    add_attack_to_catalog(data, create_attack_entry("Normal extra", "normal", 1, ""))
    ok, msg = assign_attack_to_card(data, "Daniel", "normal_extra")
    assert not ok
    assert "normal assignment limit" in msg

    for idx, typ in enumerate(("parry", "dodge", "tank", "block")):
        add_attack_to_catalog(data, create_attack_entry(f"Defense {idx}", typ, 0, ""))
        ok, _ = assign_attack_to_card(data, "Daniel", f"defense_{idx}")
        assert ok
    add_attack_to_catalog(data, create_attack_entry("Defense extra", "block", 0, ""))
    ok, msg = assign_attack_to_card(data, "Daniel", "defense_extra")
    assert not ok
    assert "Defense assignment limit" in msg


def test_deleting_attack_removes_it_from_all_cards() -> None:
    data = {
        "cards": {
            "A": {"name": "A", "attacks": ["jab", "kick"]},
            "B": {"name": "B", "attacks": ["jab"]},
            "C": {"name": "C", "attacks": ["kick"]},
        }
    }
    touched = remove_attack_from_all_cards(data, "jab")
    assert touched == 2
    assert data["cards"]["A"]["attacks"] == ["kick"]
    assert data["cards"]["B"]["attacks"] == []
    assert data["cards"]["C"]["attacks"] == ["kick"]
