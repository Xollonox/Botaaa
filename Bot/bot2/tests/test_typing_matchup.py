from bot.utils.typing_matchup import (
    defensive_multiplier,
    normalize_typing,
    parse_typing_input,
    relations_table,
    type_multiplier,
)


# ── normalization ────────────────────────────────────────────────────────────

def test_normalize_typing_titlecases_and_dedups():
    assert normalize_typing(["tank", "TANK", "fighter"]) == ["Tank", "Fighter"]


def test_normalize_typing_caps_at_two():
    assert normalize_typing(["Tank", "Fighter", "Brawler"]) == ["Tank", "Fighter"]


def test_normalize_typing_drops_unknown():
    assert normalize_typing(["Tank", "Wizard"]) == ["Tank"]


def test_parse_input_accepts_csv_and_slash():
    assert parse_typing_input("tank, brawler") == ["Tank", "Brawler"]
    assert parse_typing_input("tank/brawler") == ["Tank", "Brawler"]


# ── 1v1 baseline ─────────────────────────────────────────────────────────────

def test_1v1_no_relation_is_neutral():
    assert type_multiplier(["Tank"], ["Fighter"]) == 1.0
    assert defensive_multiplier(["Tank"], ["Fighter"]) == 1.0


def test_1v1_speedster_vs_tank_only_defensive_applies():
    # Speedster attacker → Tank defender: spec says Tank takes 30% LESS
    assert type_multiplier(["Speedster"], ["Tank"]) == 1.0
    assert defensive_multiplier(["Speedster"], ["Tank"]) == 0.70


def test_1v1_assassin_vs_tank_offensive_amplifies():
    assert type_multiplier(["Assassin"], ["Tank"]) == 1.30


def test_1v1_brawler_vs_fighter_both_sided():
    # Brawler deals 15% more and takes 15% less from Fighter
    assert type_multiplier(["Brawler"], ["Fighter"]) == 1.15
    # Symmetric: Fighter attacker → Brawler defender: 15% less dmg out + 15% less in
    assert type_multiplier(["Fighter"], ["Brawler"]) == 0.85
    assert defensive_multiplier(["Fighter"], ["Brawler"]) == 0.85


# ── AB vs C cases ────────────────────────────────────────────────────────────

def test_AB_vs_C_case1_no_relations():
    assert type_multiplier(["Tank", "Fighter"], ["Mastermind"]) == 1.0


def test_AB_vs_C_case2_only_one_type_has_relation():
    # Assassin/Mastermind attacker vs Tank: only Assassin→Tank counts
    assert type_multiplier(["Assassin", "Mastermind"], ["Tank"]) == 1.30


def test_AB_vs_C_case3_both_types_have_relation_to_C():
    # Speedster + Assassin both vs Tank: defensive on Tank (×0.70) + offensive Assassin (×1.30)
    assert type_multiplier(["Speedster", "Assassin"], ["Tank"]) == 1.30
    assert defensive_multiplier(["Speedster", "Assassin"], ["Tank"]) == 0.70


# ── AB vs CD cases ──────────────────────────────────────────────────────────

def test_AB_vs_CD_case1_both_advantages_stack():
    # Speedster + Assassin vs Brawler + Tank
    # Speedster→Brawler ×1.30, Assassin→Tank ×1.30 → 1.69
    assert round(type_multiplier(["Speedster", "Assassin"], ["Brawler", "Tank"]), 4) == 1.69


def test_AB_vs_CD_case2_advantage_and_disadvantage():
    # Brawler attacker (+1.15 vs Fighter) paired with Fighter (-0.85 vs Brawler)
    # vs Fighter + Brawler defender. Brawler→Fighter=1.15, Fighter→Brawler=0.85
    # Other pairs neutral. Product = 1.15 * 0.85 = 0.9775
    assert round(type_multiplier(["Brawler", "Fighter"], ["Fighter", "Brawler"]), 4) == 1.0
    # Note: set equality → nullify. Test a non-shared pair instead:
    assert round(type_multiplier(["Brawler", "Tank"], ["Fighter", "Speedster"]), 4) == 1.15


def test_AB_vs_CD_case3_shared_type_falls_through_to_remaining_pair():
    # Card1 (Tank, Speedster) vs Card2 (Tank, Brawler) — shared Tank, remaining Speedster→Brawler ×1.30
    assert type_multiplier(["Tank", "Speedster"], ["Tank", "Brawler"]) == 1.30


def test_AB_vs_CD_case4_identical_two_type_sets_nullify():
    assert type_multiplier(["Brawler", "Speedster"], ["Speedster", "Brawler"]) == 1.0
    assert defensive_multiplier(["Brawler", "Speedster"], ["Speedster", "Brawler"]) == 1.0


# ── mastermind neutrality ────────────────────────────────────────────────────

def test_mastermind_has_no_matchup_effect():
    assert type_multiplier(["Mastermind"], ["Tank"]) == 1.0
    assert type_multiplier(["Tank"], ["Mastermind"]) == 1.0
    assert defensive_multiplier(["Mastermind"], ["Tank"]) == 1.0


# ── relations table sanity ────────────────────────────────────────────────────

def test_relations_table_lists_known_pairs():
    rows = relations_table()
    pairs = {(at, dt) for at, dt, _, _ in rows}
    assert ("Speedster", "Tank") in pairs
    assert ("Assassin", "Tank") in pairs
    assert ("Brawler", "Fighter") in pairs
    assert ("Fighter", "Brawler") in pairs
