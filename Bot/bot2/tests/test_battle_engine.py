"""Unit tests for battle engine core formulas."""

from __future__ import annotations

import random
import math

import pytest

from bot.utils.battle_engine_pdf import (
    calc_damage,
    calc_defense_reduction,
    normalize_attack_type,
)

from bot.utils.battle_state import (
    _get_technique_bonus_multiplier,
    _strength_bonus,
    _elo_delta_cpu,
    _build_hp,
    _rank_from_trophies,
    _pvp_trophy_delta,
    _ultimate_limit_for_team,
    calculate_stat_damage,
    REJECTION_THRESHOLD,
)


class TestNormalizeAttackType:
    def test_canonical_types(self) -> None:
        assert normalize_attack_type("normal") == "normal"
        assert normalize_attack_type("special") == "special"
        assert normalize_attack_type("ultimate") == "ultimate"
        assert normalize_attack_type("unique_skill") == "unique_skill"
        assert normalize_attack_type("unique_path") == "unique_path"

    def test_defense_types(self) -> None:
        assert normalize_attack_type("block") == "block"
        assert normalize_attack_type("dodge") == "dodge"
        assert normalize_attack_type("parry") == "parry"
        assert normalize_attack_type("revert") == "revert"
        assert normalize_attack_type("tank") == "tank"

    def test_case_and_whitespace(self) -> None:
        assert normalize_attack_type("  NORMAL  ") == "normal"
        assert normalize_attack_type("Special") == "special"
        assert normalize_attack_type("ULTIMATE") == "ultimate"

    def test_hyphen_to_underscore(self) -> None:
        assert normalize_attack_type("unique-skill") == "unique_skill"
        assert normalize_attack_type("unique_path") == "unique_path"

    def test_unknown_falls_back_to_normal(self) -> None:
        assert normalize_attack_type("garbage") == "normal"
        assert normalize_attack_type("") == "normal"

    def test_switch_and_forfeit(self) -> None:
        assert normalize_attack_type("switch") == "switch"
        assert normalize_attack_type("forfeit") == "forfeit"


class TestCalcDamage:
    def test_basic_normal(self) -> None:
        dmg = calc_damage(
            {"strength": 50}, {"endurance": 30},
            attack_type="normal", attack_power=10,
        )
        assert dmg > 0

    def test_zero_defense_clamped(self) -> None:
        dmg = calc_damage(
            {"strength": 50}, {"endurance": 0},
            attack_type="normal", attack_power=10,
        )
        assert dmg >= 1

    def test_zero_power_clamped(self) -> None:
        dmg = calc_damage(
            {"strength": 50}, {"endurance": 30},
            attack_type="normal", attack_power=0,
        )
        assert dmg >= 1

    def test_high_defense_reduces_but_still_positive(self) -> None:
        dmg = calc_damage(
            {"strength": 50}, {"endurance": 500},
            attack_type="normal", attack_power=10,
        )
        assert 1 <= dmg <= 30

    def test_special_uses_technique(self) -> None:
        dmg = calc_damage(
            {"technique": 80, "strength": 10}, {"endurance": 30},
            attack_type="special", attack_power=10,
        )
        assert dmg >= 1

    def test_ultimate_uses_battle_iq(self) -> None:
        dmg = calc_damage(
            {"battle_iq": 90}, {"endurance": 30},
            attack_type="ultimate", attack_power=10,
        )
        assert dmg >= 1

    def test_damage_scales_with_power(self) -> None:
        dmg_low = calc_damage(
            {"strength": 50}, {"endurance": 30},
            attack_type="normal", attack_power=10,
        )
        dmg_high = calc_damage(
            {"strength": 50}, {"endurance": 30},
            attack_type="normal", attack_power=100,
        )
        assert dmg_high > dmg_low

    def test_damage_scales_with_attacker_stat(self) -> None:
        dmg_low = calc_damage(
            {"strength": 10}, {"endurance": 30},
            attack_type="normal", attack_power=10,
        )
        dmg_high = calc_damage(
            {"strength": 100}, {"endurance": 30},
            attack_type="normal", attack_power=10,
        )
        assert dmg_high > dmg_low


class TestCalcDefenseReduction:
    def test_block_reduces_to_40_percent(self) -> None:
        reduced = calc_defense_reduction("block", 100)
        assert reduced == max(0, int(100 * 0.4))

    def test_block_handles_zero(self) -> None:
        assert calc_defense_reduction("block", 0) == 0

    def test_parry_reduces_to_20_percent(self) -> None:
        reduced = calc_defense_reduction("parry", 100)
        assert reduced == max(0, int(100 * 0.2))

    def test_revert_reduces_to_60_percent(self) -> None:
        reduced = calc_defense_reduction("revert", 100)
        assert reduced == max(0, int(100 * 0.6))

    def test_dodge_with_seed(self) -> None:
        random.seed(42)
        results = [calc_defense_reduction("dodge", 100) for _ in range(100)]
        dodged = sum(1 for r in results if r == 0)
        assert 30 <= dodged <= 70  # roughly 50%

    def test_no_defense_passes_through(self) -> None:
        assert calc_defense_reduction("nonexistent", 100) == 100


class TestTechniqueBonusMultiplier:
    def test_low_technique_normal(self) -> None:
        m = _get_technique_bonus_multiplier(30, "normal")
        assert m == 1.04

    def test_high_technique_normal(self) -> None:
        m = _get_technique_bonus_multiplier(96, "normal")
        assert m == 1.15

    def test_ultimate_bonus(self) -> None:
        m_low = _get_technique_bonus_multiplier(30, "ultimate")
        m_high = _get_technique_bonus_multiplier(96, "ultimate")
        assert m_low == 1.10
        assert m_high == 1.30

    def test_special_bonus(self) -> None:
        m = _get_technique_bonus_multiplier(70, "special")
        assert m == 1.10

    def test_boundary_50(self) -> None:
        assert _get_technique_bonus_multiplier(49, "normal") == 1.04
        assert _get_technique_bonus_multiplier(50, "normal") == 1.06

    def test_boundary_90(self) -> None:
        assert _get_technique_bonus_multiplier(90, "normal") == 1.08
        assert _get_technique_bonus_multiplier(91, "normal") == 1.10


class TestStrengthBonus:
    def test_no_bonus_low_strength(self) -> None:
        b = _strength_bonus(50, "normal", False)
        assert b == 0

    def test_mastery_bonus_normal(self) -> None:
        b = _strength_bonus(50, "normal", True)
        assert b == 10

    def test_mastery_bonus_ultimate(self) -> None:
        b = _strength_bonus(50, "ultimate", True)
        assert b == 30

    def test_over_100_normal(self) -> None:
        b = _strength_bonus(120, "normal", False)
        assert b == 20

    def test_over_100_ultimate(self) -> None:
        b = _strength_bonus(120, "ultimate", False)
        assert b == 50

    def test_defense_type_no_bonus(self) -> None:
        assert _strength_bonus(150, "block", True) == 0


class TestBuildHP:
    def test_basic(self) -> None:
        hp = _build_hp({"endurance": 50}, [])
        assert hp == 50 * 7  # no mastery

    def test_endurance_mastery(self) -> None:
        hp = _build_hp({"endurance": 50}, ["endurance"])
        assert hp == 50 * 8

    def test_other_mastery_no_effect(self) -> None:
        hp = _build_hp({"endurance": 50}, ["strength"])
        assert hp == 50 * 7

    def test_minimum_hp(self) -> None:
        hp = _build_hp({"endurance": 0}, [])
        assert hp == 1


class TestRankFromTrophies:
    @pytest.mark.parametrize("trophies,expected", [
        (0, "Copper"), (150, "Copper"),
        (200, "Iron"), (350, "Iron"),
        (400, "Bronze"), (750, "Bronze"),
        (800, "Silver"), (1100, "Silver"),
        (1200, "Gold"), (1500, "Gold"),
        (1600, "Diamond"), (2200, "Diamond"),
        (2400, "Platinum"), (3000, "Platinum"),
        (3200, "Sapphire"), (3800, "Sapphire"),
        (4000, "Ruby"), (10000, "Ruby"),
    ])
    def test_rank_thresholds(self, trophies: int, expected: str) -> None:
        assert _rank_from_trophies(trophies) == expected


class TestUltimateLimitForTeam:
    def test_sizes(self) -> None:
        assert _ultimate_limit_for_team(1) == 1
        assert _ultimate_limit_for_team(2) == 1
        assert _ultimate_limit_for_team(3) == 2
        assert _ultimate_limit_for_team(4) == 3
        assert _ultimate_limit_for_team(5) == 3


class TestEloDeltaCpu:
    def test_equal_trophies_win(self) -> None:
        delta = _elo_delta_cpu(1000, 1000, True)
        assert 4 <= delta <= 22

    def test_equal_trophies_loss(self) -> None:
        delta = _elo_delta_cpu(1000, 1000, False)
        assert -22 <= delta <= -4

    def test_low_ranked_win(self) -> None:
        delta = _elo_delta_cpu(300, 1000, True)
        assert delta > 4  # higher k-factor

    def test_high_ranked_win(self) -> None:
        delta = _elo_delta_cpu(2500, 1000, True)
        assert delta <= 16  # lower k-factor

    def test_underdog_wins_bigger_gain(self) -> None:
        low_win = _elo_delta_cpu(800, 1200, True)
        high_win = _elo_delta_cpu(1200, 800, True)
        assert low_win > high_win


class TestPvpTrophyDelta:
    def test_equal_draw(self) -> None:
        da, db = _pvp_trophy_delta(1000, 1000, "draw")
        assert da == 10
        assert db == 10

    def test_equal_winner_gains(self) -> None:
        da, db = _pvp_trophy_delta(1000, 1000, "A")
        assert 25 <= da <= 40
        assert -40 <= db <= -25
        assert da + db == 0  # zero-sum

    def test_higher_wins(self) -> None:
        da, db = _pvp_trophy_delta(1500, 1000, "A")
        assert 20 <= da <= 30
        assert -30 <= db <= -20
        assert da + db == 0

    def test_lower_wins_upset(self) -> None:
        da, db = _pvp_trophy_delta(1500, 1000, "B")
        assert -50 <= da <= -30
        assert 30 <= db <= 50
        assert da + db == 0

    def test_draw_with_diff(self) -> None:
        da, db = _pvp_trophy_delta(1500, 1000, "draw")
        assert 10 <= da <= 20
        assert -10 <= db <= 0


class TestCalculateStatDamage:
    def test_returns_damage_and_detail(self) -> None:
        atk = {"strength": 50, "biq": 50, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        dfs = {"biq": 30, "iq": 0, "endurance": 30, "speed": 30}
        dmg, detail = calculate_stat_damage(atk, dfs, "normal")
        assert isinstance(dmg, int)
        assert dmg >= 0
        assert isinstance(detail, dict)
        assert "miss" in detail
        assert "final_damage" in detail

    def test_higher_biq_avoid_miss(self) -> None:
        atk = {"strength": 50, "biq": 80, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        dfs = {"biq": 10, "iq": 0, "endurance": 30, "speed": 30}
        dmg, detail = calculate_stat_damage(atk, dfs, "normal")
        assert detail["miss"] is False
        assert dmg > 0

    def test_lower_biq_can_miss(self) -> None:
        atk = {"strength": 50, "biq": 10, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        dfs = {"biq": 80, "iq": 0, "endurance": 30, "speed": 30}
        misses = 0
        trials = 200
        for _ in range(trials):
            dmg, detail = calculate_stat_damage(atk, dfs, "normal")
            if detail.get("miss"):
                misses += 1
        assert misses > 0, "Should miss some of the time"

    def test_special_does_more_than_normal(self) -> None:
        atk = {"strength": 100, "biq": 50, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        dfs = {"biq": 10, "iq": 0, "endurance": 30, "speed": 30}
        random.seed(12345)
        dmg_normal, _ = calculate_stat_damage(atk, dfs, "normal")
        random.seed(12345)
        dmg_special, _ = calculate_stat_damage(atk, dfs, "special")
        assert dmg_special > dmg_normal

    def test_ultimate_does_more_than_special(self) -> None:
        atk = {"strength": 100, "biq": 50, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        dfs = {"biq": 10, "iq": 0, "endurance": 30, "speed": 30}
        random.seed(54321)
        dmg_special, _ = calculate_stat_damage(atk, dfs, "special")
        random.seed(54321)
        dmg_ult, _ = calculate_stat_damage(atk, dfs, "ultimate")
        assert dmg_ult > dmg_special

    def test_miss_returns_zero_damage(self) -> None:
        atk = {"strength": 50, "biq": 1, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        dfs = {"biq": 99, "iq": 0, "endurance": 30, "speed": 30}
        random.seed(1)
        dmg, detail = calculate_stat_damage(atk, dfs, "normal")
        if detail.get("miss"):
            assert dmg == 0

    def test_iq_boosts_damage(self) -> None:
        atk_low = {"strength": 50, "biq": 50, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        atk_high = {"strength": 50, "biq": 50, "technique": 50, "iq": 100, "speed": 50, "endurance": 50}
        dfs = {"biq": 10, "iq": 0, "endurance": 30, "speed": 30}
        random.seed(999)
        dmg_low, _ = calculate_stat_damage(atk_low, dfs, "normal")
        random.seed(999)
        dmg_high, _ = calculate_stat_damage(atk_high, dfs, "normal")
        assert dmg_high >= dmg_low  # iq bonus is a multiplier

    def test_strength_mastery_increases_damage(self) -> None:
        atk = {"strength": 80, "biq": 50, "technique": 50, "iq": 0, "speed": 50, "endurance": 50}
        atk_with_mastery = {"strength": 80, "biq": 50, "technique": 50, "iq": 0, "speed": 50, "endurance": 50, "mastery": ["strength"]}
        dfs = {"biq": 10, "iq": 0, "endurance": 30, "speed": 30}
        random.seed(777)
        dmg, _ = calculate_stat_damage(atk, dfs, "normal")
        random.seed(777)
        dmg_m, _ = calculate_stat_damage(atk_with_mastery, dfs, "normal")
        assert dmg_m >= dmg
