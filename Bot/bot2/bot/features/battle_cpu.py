"""CPU move-picker logic extracted from BattleCog.

Pure logic — no discord API surface. Functions take the cog as a first arg
when they need access to per-battle helpers on the cog (attack row lookup,
active fighter uid).
"""

from __future__ import annotations

import random
from typing import Any

from bot.utils.battle_engine_pdf import normalize_attack_type


def _cpu_pick_move(personality: str, available_moves: list, fighter_hp_pct: float, enemy_hp_pct: float, fighter_stamina: int = 100) -> str:
    """Pick a move for the CPU based on personality.

    Args:
        personality: personality name string
        available_moves: list of move type strings that still have uses
            (e.g. ["normal", "special", "ultimate", "block", "dodge"])
        fighter_hp_pct: current fighter's HP as 0.0-1.0
        enemy_hp_pct: enemy fighter's HP as 0.0-1.0
        fighter_stamina: current stamina of active CPU fighter
    Returns:
        move type string to use
    """
    if fighter_stamina <= 0:
        return "normal"

    has_special = "special" in available_moves
    has_ultimate = "ultimate" in available_moves
    has_block = "block" in available_moves
    has_dodge = "dodge" in available_moves

    p = personality.lower() if personality else "balanced"

    if p == "aggressive":
        # Always use the most powerful move available
        if has_ultimate:
            return "ultimate"
        if has_special:
            return "special"
        return "normal"

    elif p == "defensive":
        # Block when damaged, dodge when critical, otherwise normal
        if has_block and fighter_hp_pct < 0.7:
            return "block"
        if has_dodge and fighter_hp_pct < 0.5:
            return "dodge"
        return "normal"

    elif p == "trickster":
        # Dodge when healthy, attack unpredictably
        if has_dodge and fighter_hp_pct > 0.6 and random.random() < 0.4:
            return "dodge"
        if has_special and random.random() < 0.5:
            return "special"
        pool = [m for m in available_moves if m in ("normal", "special", "block")] or ["normal"]
        return random.choice(pool)

    elif p == "finisher":
        # Save ultimate for when enemy is low
        if has_ultimate and enemy_hp_pct < 0.3:
            return "ultimate"
        if has_special and enemy_hp_pct < 0.5:
            return "special"
        if has_block and fighter_hp_pct < 0.4:
            return "block"
        return "normal"

    else:  # "balanced" or unknown
        # Mix of offense and defense
        if has_ultimate and fighter_hp_pct > 0.5 and random.random() < 0.3:
            return "ultimate"
        if has_special and random.random() < 0.4:
            return "special"
        if has_block and fighter_hp_pct < 0.5 and random.random() < 0.3:
            return "block"
        return "normal"


def choose_cpu_move(cog: Any, data: dict[str, Any], battle_id: str, cpu_id: str, enemy_id: str) -> tuple[str, str]:
    battle = cog._battle_root(data).get("active", {}).get(battle_id)
    if not isinstance(battle, dict):
        return "normal", "normal"

    cpu_state = (battle.get("players", {}) or {}).get(cpu_id, {})
    enemy_state = (battle.get("players", {}) or {}).get(enemy_id, {})
    offensive, defensive = cog._fighter_attack_rows(data, battle_id, cpu_id)
    enemy_offensive, _enemy_defensive = cog._fighter_attack_rows(data, battle_id, enemy_id)
    personality = str((cpu_state.get("cpu_meta", {}) or {}).get("personality", "Balanced")) if isinstance(cpu_state, dict) else "Balanced"
    cpu_uid = cog._current_uid(cpu_state) if isinstance(cpu_state, dict) else ""
    ene_uid = cog._current_uid(enemy_state) if isinstance(enemy_state, dict) else ""

    cpu_hp = int((cpu_state.get("hp", {}) or {}).get(cpu_uid, 1)) if isinstance(cpu_state, dict) else 1
    cpu_hp_max = max(1, int((cpu_state.get("hp_max", {}) or {}).get(cpu_uid, 1))) if isinstance(cpu_state, dict) else 1
    ene_hp = int((enemy_state.get("hp", {}) or {}).get(ene_uid, 1)) if isinstance(enemy_state, dict) else 1
    ene_hp_max = max(1, int((enemy_state.get("hp_max", {}) or {}).get(ene_uid, 1))) if isinstance(enemy_state, dict) else 1
    hp_pct = (cpu_hp / cpu_hp_max) * 100
    enemy_pct = (ene_hp / ene_hp_max) * 100

    pending = (battle.get("pending_defense_by_char_uid", {}) or {}).get(cpu_uid) if isinstance(battle.get("pending_defense_by_char_uid", {}), dict) else None
    side_last_group = str((battle.get("last_move_group_by_side", {}) or {}).get(cpu_id, "")) if isinstance(battle.get("last_move_group_by_side", {}), dict) else ""
    if not side_last_group:
        side_last_group = str((battle.get("last_move_group_by_char_uid", {}) or {}).get(cpu_uid, "")) if isinstance(battle.get("last_move_group_by_char_uid", {}), dict) else ""
    special_allowed = side_last_group != "special_like"

    used_ult = int((battle.get("used_ultimate_count_by_side", {}) or {}).get(cpu_id, 0)) if isinstance(battle.get("used_ultimate_count_by_side", {}), dict) else 0
    used_ult_by_char = bool((battle.get("used_ultimate_by_char_uid", {}) or {}).get(cpu_uid, False)) if isinstance(battle.get("used_ultimate_by_char_uid", {}), dict) else False
    team_uids = cpu_state.get("team_uids", []) if isinstance(cpu_state.get("team_uids"), list) else []
    ult_limit = 3 if len(team_uids) >= 4 else (2 if len(team_uids) == 3 else 1)

    cpu_stats = (cpu_state.get("stats", {}) or {}).get(cpu_uid, {}) if isinstance(cpu_state.get("stats", {}), dict) else {}
    enemy_stats = (enemy_state.get("stats", {}) or {}).get(ene_uid, {}) if isinstance(enemy_state.get("stats", {}), dict) else {}
    cpu_speed = int((cpu_stats or {}).get("speed", 0)) if isinstance(cpu_stats, dict) else 0
    cpu_end = int((cpu_stats or {}).get("endurance", 0)) if isinstance(cpu_stats, dict) else 0
    cpu_tec = int((cpu_stats or {}).get("technique", 0)) if isinstance(cpu_stats, dict) else 0
    enemy_speed = int((enemy_stats or {}).get("speed", 0)) if isinstance(enemy_stats, dict) else 0
    enemy_str = int((enemy_stats or {}).get("strength", 0)) if isinstance(enemy_stats, dict) else 0
    enemy_tec = int((enemy_stats or {}).get("technique", 0)) if isinstance(enemy_stats, dict) else 0

    def row_score(row: dict[str, Any]) -> int:
        typ = normalize_attack_type(str(row.get("type", "normal")))
        power = row.get("power")
        if isinstance(power, int):
            base = int(power)
        elif isinstance(power, str) and power.strip().lstrip("-").isdigit():
            base = int(power.strip())
        else:
            base_map = {
                "normal": 28,
                "special": 54,
                "ultimate": 82,
                "unique_skill": 68,
                "unique_path": 66,
                "block": 42,
                "dodge": 44,
                "revert": 48,
                "parry": 46,
            }
            base = base_map.get(typ, 25)
        if typ == "ultimate":
            base += 12
        elif typ in {"unique_skill", "unique_path"}:
            base += 8
        elif typ == "special":
            base += 4
        left = int(row.get("left", -1))
        if left == 1 and typ in {"ultimate", "unique_skill", "unique_path", "block", "dodge", "revert", "parry"}:
            base += 3
        return base

    def best(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=row_score, reverse=True)

    def pick_best(rows: list[dict[str, Any]], fallback: str) -> tuple[str, str]:
        ordered = best(rows)
        if ordered:
            row = ordered[0]
            return normalize_attack_type(str(row.get("type", fallback))), str(row.get("key", fallback))
        return fallback, fallback

    normals = best([r for r in offensive if normalize_attack_type(str(r.get("type", "normal"))) == "normal"])
    specials = best([r for r in offensive if normalize_attack_type(str(r.get("type", "normal"))) in {"special", "unique_skill", "unique_path"}])
    ultimates = best([
        r for r in offensive
        if normalize_attack_type(str(r.get("type", "normal"))) == "ultimate" and used_ult < ult_limit and not used_ult_by_char
    ])
    used_defs_map = battle.get("used_defenses_by_char_uid", {}) if isinstance(battle.get("used_defenses_by_char_uid", {}), dict) else {}
    raw_used_defs = used_defs_map.get(cpu_uid, set())
    if isinstance(raw_used_defs, set):
        used_defs = {normalize_attack_type(str(x)) for x in raw_used_defs}
    elif isinstance(raw_used_defs, list):
        used_defs = {normalize_attack_type(str(x)) for x in raw_used_defs}
    else:
        used_defs = set()

    defs = best([
        r for r in (defensive if not pending else [])
        if normalize_attack_type(str(r.get("type", ""))) not in used_defs
    ])
    best_normal_score = row_score(normals[0]) if normals else -1
    best_special_score = row_score(specials[0]) if specials else -1
    best_ultimate_score = row_score(ultimates[0]) if ultimates else -1
    enemy_pressure = max((row_score(r) for r in enemy_offensive), default=30)
    enemy_end = int((enemy_stats or {}).get("endurance", 0)) if isinstance(enemy_stats, dict) else 0
    cpu_hp_pct = hp_pct

    defense_map = {normalize_attack_type(str(r.get("type", ""))): r for r in defs}

    def choose_defense() -> str | None:
        if not defs:
            return None
        if "dodge" in defense_map and cpu_speed >= enemy_speed:
            return str(defense_map["dodge"].get("key", "dodge"))
        if "revert" in defense_map and cpu_tec >= enemy_str:
            return str(defense_map["revert"].get("key", "revert"))
        if "parry" in defense_map and cpu_tec >= enemy_tec:
            return str(defense_map["parry"].get("key", "parry"))
        if "block" in defense_map and cpu_end >= enemy_str:
            return str(defense_map["block"].get("key", "block"))
        ordered_pref = ["dodge", "revert", "parry", "block"] if personality == "Trickster" else ["block", "parry", "revert", "dodge"]
        for key in ordered_pref:
            if key in defense_map:
                return str(defense_map[key].get("key", key))
        return str(defs[0].get("key", "block"))

    defense_choice = choose_defense()
    switch_choice: str | None = None
    switch_score = -1.0
    switch_hp_gain = 0.0

    if defense_choice and (hp_pct <= 30 or (enemy_pressure >= 75 and hp_pct <= 45)):
        return defense_choice, defense_choice

    if special_allowed:
        if ultimates and (enemy_pct <= 58 or best_ultimate_score >= best_normal_score + 24):
            if personality in {"Aggressive", "Finisher"} or random.random() < 0.72:
                return pick_best(ultimates, "normal")
        if specials and (enemy_pct <= 72 or best_special_score >= best_normal_score + 12):
            if personality == "Finisher" and ultimates and enemy_pct <= 45 and random.random() < 0.85:
                return pick_best(ultimates, "normal")
            if personality in {"Aggressive", "Finisher", "Trickster"} or random.random() < 0.62:
                return pick_best(specials, "normal")

    if defense_choice and hp_pct <= 50:
        defensive_bias = {
            "Defensive": 0.65,
            "Balanced": 0.38,
            "Trickster": 0.48,
            "Aggressive": 0.22,
            "Finisher": 0.18,
        }.get(personality, 0.35)
        if random.random() < defensive_bias:
            return defense_choice, defense_choice

    if not special_allowed:
        legal_choices: list[tuple[str, str]] = []
        legal_weights: list[int] = []

        def add_legal(move_type: str, value: str, weight: int) -> None:
            if weight > 0 and value:
                legal_choices.append((move_type, value))
                legal_weights.append(weight)

        if normals:
            normal_weight = 7
            if hp_pct <= 40:
                normal_weight -= 1
            if personality == "Aggressive":
                normal_weight += 1
            elif personality == "Defensive":
                normal_weight -= 2
            elif personality == "Trickster":
                normal_weight -= 1
            add_legal(*pick_best(normals, "normal"), max(2, normal_weight))

        if defense_choice:
            defense_weight = 6
            if hp_pct <= 55:
                defense_weight += 3
            if enemy_pressure >= 70:
                defense_weight += 2
            if personality == "Defensive":
                defense_weight += 4
            elif personality == "Trickster":
                defense_weight += 2
            add_legal(defense_choice, defense_choice, max(1, defense_weight))

        if switch_choice:
            switch_weight = 4
            if hp_pct <= 50:
                switch_weight += 2
            if enemy_pressure >= 72:
                switch_weight += 2
            if personality in {"Defensive", "Trickster"}:
                switch_weight += 2
            add_legal("switch", switch_choice, max(1, switch_weight))

        if legal_choices:
            return random.choices(legal_choices, weights=legal_weights, k=1)[0]
        if normals:
            return pick_best(normals, "normal")
        if defense_choice:
            return defense_choice, defense_choice

    if personality == "Defensive" and defense_choice and random.random() < 0.30:
        return defense_choice, defense_choice
    if personality == "Trickster" and specials and special_allowed and random.random() < 0.58:
        return pick_best(specials, "normal")
    if personality in {"Aggressive", "Finisher"} and ultimates and special_allowed and random.random() < 0.48:
        return pick_best(ultimates, "normal")
    if personality in {"Aggressive", "Finisher", "Balanced"} and specials and special_allowed and random.random() < 0.55:
        return pick_best(specials, "normal")

    def fighter_score(uid: str, side_state: dict[str, Any]) -> float:
        stats_map = side_state.get("stats", {}) if isinstance(side_state.get("stats"), dict) else {}
        hp_map = side_state.get("hp", {}) if isinstance(side_state.get("hp"), dict) else {}
        hp_max_map = side_state.get("hp_max", {}) if isinstance(side_state.get("hp_max"), dict) else {}
        stats = stats_map.get(uid, {}) if isinstance(stats_map.get(uid, {}), dict) else {}
        cur_hp = int(hp_map.get(uid, 0))
        max_hp = max(1, int(hp_max_map.get(uid, 1)))
        hp_ratio = (cur_hp / max_hp) * 100
        strength = int(stats.get("strength", 0))
        speed = int(stats.get("speed", 0))
        endurance = int(stats.get("endurance", 0))
        technique = int(stats.get("technique", 0))
        iq = int(stats.get("iq", 0))
        biq = int(stats.get("biq", 0))
        base = hp_ratio * 0.40 + strength * 1.05 + speed * 1.10 + endurance * 1.20 + technique * 1.00 + iq * 0.45 + biq * 0.45
        matchup = max(0, strength - enemy_str) * 0.25 + max(0, speed - enemy_speed) * 0.35 + max(0, technique - enemy_tec) * 0.30 + max(0, endurance - enemy_end) * 0.20
        return base + matchup

    current_score = fighter_score(cpu_uid, cpu_state) if cpu_uid else 0.0
    if isinstance(team_uids, list) and len(team_uids) > 1:
        hp_map = cpu_state.get("hp", {}) if isinstance(cpu_state.get("hp"), dict) else {}
        hp_max_map = cpu_state.get("hp_max", {}) if isinstance(cpu_state.get("hp_max"), dict) else {}
        stats_map = cpu_state.get("stats", {}) if isinstance(cpu_state.get("stats"), dict) else {}
        for uid in team_uids:
            if str(uid) == cpu_uid:
                continue
            cur_hp = int(hp_map.get(uid, 0))
            if cur_hp <= 0:
                continue
            max_hp = max(1, int(hp_max_map.get(uid, 1)))
            stats = stats_map.get(uid, {}) if isinstance(stats_map.get(uid, {}), dict) else {}
            candidate_score = fighter_score(str(uid), cpu_state)
            hp_gain = (cur_hp / max_hp) * 100 - cpu_hp_pct
            if candidate_score > switch_score:
                switch_choice = str(uid)
                switch_score = candidate_score
                switch_hp_gain = hp_gain
        if switch_choice is not None:
            switch_gain = switch_score - current_score
            switch_threshold = 18.0
            if personality in {"Defensive", "Trickster"}:
                switch_threshold -= 4.0
            elif personality == "Aggressive":
                switch_threshold += 4.0
            if hp_pct <= 35:
                switch_threshold -= 6.0
            elif hp_pct <= 50:
                switch_threshold -= 2.0
            if enemy_pressure >= 72:
                switch_threshold -= 4.0
            if switch_gain >= 30:
                switch_threshold -= 5.0
            elif switch_gain >= 15:
                switch_threshold -= 2.0
            if switch_gain < switch_threshold and not (hp_pct <= 30 and switch_hp_gain >= 15):
                switch_choice = None

    choices: list[tuple[str, str]] = []
    weights: list[int] = []

    def add_choice(move_type: str, value: str, weight: int) -> None:
        if weight > 0 and value:
            choices.append((move_type, value))
            weights.append(weight)

    if normals:
        normal_weight = 9
        if side_last_group == "normal_or_defensive":
            normal_weight -= 2
        if any([specials, ultimates, defense_choice, switch_choice]):
            normal_weight -= 2
        if personality == "Aggressive":
            normal_weight += 1
        elif personality == "Defensive":
            normal_weight -= 1
        elif personality == "Trickster":
            normal_weight -= 1
        add_choice(*pick_best(normals, "normal"), max(2, normal_weight))

    if special_allowed and specials:
        special_weight = 10
        if enemy_pct <= 75:
            special_weight += 3
        if best_special_score >= best_normal_score + 6:
            special_weight += 4
        if side_last_group == "normal_or_defensive":
            special_weight += 2
        if personality in {"Aggressive", "Trickster"}:
            special_weight += 3
        elif personality == "Balanced":
            special_weight += 1
        elif personality == "Defensive":
            special_weight -= 1
        add_choice(*pick_best(specials, "normal"), max(2, special_weight))

    if special_allowed and ultimates:
        ultimate_weight = 7
        if enemy_pct <= 60:
            ultimate_weight += 4
        if enemy_pct <= 35:
            ultimate_weight += 4
        if best_ultimate_score >= best_normal_score + 10:
            ultimate_weight += 5
        if personality == "Aggressive":
            ultimate_weight += 4
        elif personality == "Finisher":
            ultimate_weight += 6 if enemy_pct <= 65 else 2
        elif personality == "Balanced":
            ultimate_weight += 1
        add_choice(*pick_best(ultimates, "normal"), max(2, ultimate_weight))

    if defense_choice:
        defense_weight = 6
        if hp_pct <= 55:
            defense_weight += 3
        if hp_pct <= 35:
            defense_weight += 5
        if enemy_pressure >= 70:
            defense_weight += 5
        if personality == "Defensive":
            defense_weight += 6
        elif personality == "Trickster":
            defense_weight += 2
        elif personality == "Aggressive":
            defense_weight -= 2
        add_choice(defense_choice, defense_choice, max(2, defense_weight))

    if switch_choice:
        switch_weight = 5
        if hp_pct <= 55:
            switch_weight += 4
        if hp_pct <= 35:
            switch_weight += 6
        if enemy_pressure >= 70:
            switch_weight += 3
        if switch_score - current_score >= 15:
            switch_weight += 4
        if switch_score - current_score >= 30:
            switch_weight += 4
        if personality == "Defensive":
            switch_weight += 4
        elif personality == "Trickster":
            switch_weight += 6
        elif personality == "Aggressive":
            switch_weight -= 2
        add_choice("switch", switch_choice, max(2, switch_weight))

    if choices:
        return random.choices(choices, weights=weights, k=1)[0]

    if normals:
        return pick_best(normals, "normal")
    if special_allowed and ultimates:
        return pick_best(ultimates, "normal")
    if special_allowed and specials:
        return pick_best(specials, "normal")
    if defense_choice:
        return defense_choice, defense_choice
    if switch_choice:
        return "switch", switch_choice
    if offensive:
        for row in best(offensive):
            typ = normalize_attack_type(str(row.get("type", "normal")))
            if typ == "switch":
                continue
            if not special_allowed and typ in {"special", "unique_skill", "unique_path", "ultimate"}:
                continue
            return typ, str(row.get("key", "normal"))
    if defensive:
        row = best(defensive)[0]
        return normalize_attack_type(str(row.get("type", "block"))), str(row.get("key", "block"))
    return "skip", ""
