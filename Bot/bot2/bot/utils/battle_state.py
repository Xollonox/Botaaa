"""Battle state management: creation, move application, and resolution."""

from __future__ import annotations

import logging
import uuid
import random
from typing import Any

from bot.utils.attacks_logic import ensure_attacks_structure
from bot.utils.battle_engine_pdf import normalize_attack_type
from bot.utils.cards_logic import compute_scaled_stats
from bot.utils.squad_logic import get_player
from bot.utils.timeutil import now_ts
from bot.utils import achievement_logic as _ach
from bot.utils.typing_matchup import (
    MASTERMIND_BIQ_BONUS,
    MASTERMIND_IQ_BONUS,
    defensive_multiplier,
    has_mastermind,
    normalize_typing,
    type_multiplier,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
REJECTION_THRESHOLD: int = 30  # stat gap above which defense is rejected

def _rank_from_trophies(trophies: int) -> str:
    if trophies >= 4000:
        return "Ruby"
    if trophies >= 3200:
        return "Sapphire"
    if trophies >= 2400:
        return "Platinum"
    if trophies >= 1600:
        return "Diamond"
    if trophies >= 1200:
        return "Gold"
    if trophies >= 800:
        return "Silver"
    if trophies >= 400:
        return "Bronze"
    if trophies >= 200:
        return "Iron"
    return "Copper"


def _get_technique_bonus_multiplier(technique: int, move_type: str) -> float:
    tec = int(technique)
    typ = normalize_attack_type(str(move_type or "normal"))
    if typ == "ultimate":
        if tec < 50:
            return 1.10
        if tec <= 70:
            return 1.13
        if tec <= 90:
            return 1.15
        if tec <= 95:
            return 1.18
        return 1.30
    if typ in {"special", "unique_skill", "unique_path"}:
        if tec < 50:
            return 1.06
        if tec <= 70:
            return 1.10
        if tec <= 90:
            return 1.12
        if tec <= 95:
            return 1.13
        return 1.18
    if tec < 50:
        return 1.04
    if tec <= 70:
        return 1.06
    if tec <= 90:
        return 1.08
    if tec <= 95:
        return 1.10
    return 1.15


def _move_group(move_type: str) -> str:
    mt = normalize_attack_type(str(move_type or "normal"))
    if mt in {"special", "ultimate", "unique_skill", "unique_path"}:
        return "special_like"
    return "normal_or_defensive"



def _ultimate_limit_for_team(team_size: int) -> int:
    size = max(1, int(team_size or 1))
    if size >= 4:
        return 3
    if size == 3:
        return 2
    return 1

def _safe_set_map(state: dict[str, Any], key: str, uid: str) -> set[str]:
    container = state.setdefault(key, {})
    if not isinstance(container, dict):
        container = {}
        state[key] = container
    raw = container.get(uid)
    if isinstance(raw, set):
        return raw
    built = {str(x) for x in raw} if isinstance(raw, list) else set()
    container[uid] = built
    return built


def _next_alive_index(side: dict[str, Any]) -> int | None:
    team = side.get("team_uids", []) if isinstance(side.get("team_uids"), list) else []
    hp = side.get("hp", {}) if isinstance(side.get("hp"), dict) else {}
    for idx, uid in enumerate(team):
        if int(hp.get(str(uid), 0)) > 0:
            return idx
    return None


def _sync_active_fighter(side: dict[str, Any]) -> str:
    """
    Ensure the side points at a living fighter whenever possible.

    Returns:
        "active_ok"       -> current fighter is still alive
        "auto_switched"   -> current fighter fainted and another fighter was promoted
        "side_eliminated" -> no fighters remain alive
    """
    team = side.get("team_uids", []) if isinstance(side.get("team_uids"), list) else []
    hp = side.get("hp", {}) if isinstance(side.get("hp"), dict) else {}
    if not team:
        return "side_eliminated"

    idx = int(side.get("active_index", side.get("current_index", 0)))
    if 0 <= idx < len(team) and int(hp.get(str(team[idx]), 0)) > 0:
        side["current_index"] = int(idx)
        side["active_index"] = int(idx)
        return "active_ok"

    next_idx = _next_alive_index(side)
    if next_idx is None:
        return "side_eliminated"

    side["current_index"] = int(next_idx)
    side["active_index"] = int(next_idx)
    return "auto_switched"


def _build_hp(stats: dict[str, int], mastery: list[str]) -> int:
    endurance = int(stats.get("endurance", 0))
    mult = 8 if any(str(m).lower() == "endurance" for m in mastery) else 7
    return max(1, endurance * mult)


def _build_cpu_side(data: dict[str, Any], team_size: int = 4, min_rarity: str = "Rare", player_trophies: int = 0) -> dict[str, Any]:
    """
    Build a CPU team side from the card catalog with star levels scaled to player rank.
    This gives the CPU its own fighters instead of borrowing the human player's cards.
    """
    cards = data.get("cards", {})
    if not isinstance(cards, dict) or not cards:
        return _build_player_side(data, "", [])

    rarity_order = {"Common": 0, "Rare": 1, "Epic": 2, "Legendary": 3,
                    "Mythical": 4, "Infernal": 5, "Abyssal": 6}
    min_rank = rarity_order.get(min_rarity, 1)

    # Build pool of eligible cards (must have stats)
    pool: list[str] = []
    for name, card in cards.items():
        if not isinstance(card, dict):
            continue
        rarity = str(card.get("rarity", "Common"))
        if rarity_order.get(rarity, 0) < min_rank:
            continue
        stats = card.get("stats", {})
        if not isinstance(stats, dict):
            continue
        total = sum(int(stats.get(k, 0)) for k in ("strength", "speed", "endurance", "technique", "iq", "battle_iq"))
        if total < 10:
            continue  # skip cards with no meaningful stats
        pool.append(name)

    if not pool:
        # Fallback: include all cards with stats
        for name, card in cards.items():
            if isinstance(card, dict):
                pool.append(name)

    if not pool:
        return _build_player_side(data, "", [])

    import random as _random
    selected_names = _random.sample(pool, min(team_size, len(pool)))

    # Build team_uids as synthetic IDs so the battle system can track them
    team_uids: list[str] = []
    hp: dict[str, int] = {}
    hp_max: dict[str, int] = {}
    stats_map: dict[str, dict[str, int]] = {}
    fighter_names: dict[str, str] = {}
    mastery_by_uid: dict[str, list[str]] = {}
    assigned_by_uid: dict[str, dict[str, list[str]]] = {}

    for card_name in selected_names:
        uid = f"cpu:{card_name.replace(' ', '_')}"
        team_uids.append(uid)

        card_def = cards.get(card_name, {})
        if not isinstance(card_def, dict):
            continue

        # Scale CPU star level based on player trophies for fair difficulty
        if player_trophies < 400:
            star_range = (1, 2)
        elif player_trophies < 1200:
            star_range = (1, 3)
        elif player_trophies < 2400:
            star_range = (2, 4)
        else:
            star_range = (3, 5)
        stars = _random.randint(*star_range)
        scaled = compute_scaled_stats(card_def, stars) if isinstance(card_def, dict) else {}
        mastery_raw = card_def.get("mastery", [])
        if isinstance(mastery_raw, list):
            mastery = [str(m).lower() for m in mastery_raw]
        elif isinstance(mastery_raw, dict):
            mastery = [str(mastery_raw.get("type", "")).lower()] if mastery_raw.get("type") else []
        else:
            mastery = []

        cur_hp = _build_hp(scaled, mastery)
        hp[uid] = cur_hp
        hp_max[uid] = cur_hp
        stats_map[uid] = {
            "strength": int(scaled.get("strength", 1)),
            "speed": int(scaled.get("speed", 1)),
            "endurance": int(scaled.get("endurance", 1)),
            "technique": int(scaled.get("technique", 1)),
            "iq": int(scaled.get("iq", 1)),
            "biq": int(scaled.get("battle_iq", scaled.get("biq", 1))),
            "typing": normalize_typing(card_def.get("typing", [])),
        }
        fighter_names[uid] = card_name
        mastery_by_uid[uid] = [str(m).lower() for m in mastery]

        # No assigned attacks for CPU — uses card_def attacks
        assigned_by_uid[uid] = {"normal": [], "special": [], "unique_skill": [], "unique_path": []}

    return {
        "team_uids": team_uids,
        "current_index": 0,
        "hp": hp,
        "hp_max": hp_max,
        "stats": stats_map,
        "fighter_names": fighter_names,
        "mastery_by_uid": mastery_by_uid,
        "assigned_attacks_by_uid": assigned_by_uid,
        "is_cpu": True,
    }


def _build_player_side(data: dict[str, Any], user_id: str, team_uids: list[str]) -> dict[str, Any]:
    player = get_player(data, user_id)
    inventory = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
    inv_map = {str(it.get("uid", "")): it for it in inventory if isinstance(it, dict)} if isinstance(inventory, list) else {}
    cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}

    hp: dict[str, int] = {}
    hp_max: dict[str, int] = {}
    stats_map: dict[str, dict[str, int]] = {}
    fighter_names: dict[str, str] = {}
    mastery_by_uid: dict[str, list[str]] = {}
    assigned_by_uid: dict[str, dict[str, list[str]]] = {}

    for uid in team_uids:
        inst = inv_map.get(uid, {})
        card_name = str(inst.get("card_name", uid[:8]))
        card_def = cards.get(card_name, {}) if isinstance(cards.get(card_name, {}), dict) else {}
        stars = int(inst.get("stars", 0))
        scaled = compute_scaled_stats(card_def, stars) if isinstance(card_def, dict) else {}
        mastery = list(card_def.get("mastery", [])) if isinstance(card_def.get("mastery", []), list) else []

        cur_hp = _build_hp(scaled, mastery)
        hp[uid] = cur_hp
        hp_max[uid] = cur_hp
        stats_map[uid] = {
            "strength": int(scaled.get("strength", 1)),
            "speed": int(scaled.get("speed", 1)),
            "endurance": int(scaled.get("endurance", 1)),
            "technique": int(scaled.get("technique", 1)),
            "iq": int(scaled.get("iq", 1)),
            "biq": int(scaled.get("battle_iq", scaled.get("biq", 1))),
            "typing": normalize_typing(card_def.get("typing", [])),
        }
        fighter_names[uid] = card_name
        mastery_by_uid[uid] = [str(m).lower() for m in mastery]

        assigned = inst.get("assigned_attacks", {}) if isinstance(inst.get("assigned_attacks", {}), dict) else {}
        assigned_by_uid[uid] = {}
        for k in ("normal", "special", "unique_skill", "unique_path"):
            vals = assigned.get(k, []) if isinstance(assigned, dict) else []
            assigned_by_uid[uid][k] = [str(v) for v in vals] if isinstance(vals, list) else []

    return {
        "team_uids": [str(x) for x in team_uids],
        "current_index": 0,
        "hp": hp,
        "hp_max": hp_max,
        "stats": stats_map,
        "fighter_names": fighter_names,
        "mastery_by_uid": mastery_by_uid,
        "assigned_attacks_by_uid": assigned_by_uid,
        "is_cpu": False,
    }


def default_uses_by_type(move_type: str) -> int | None:
    mt = normalize_attack_type(str(move_type or "normal"))
    if mt == "unique_skill":
        return 1
    if mt == "unique_path":
        return 1
    if mt in {"block", "dodge", "revert", "parry", "tank", "defensive"}:
        return 1
    return None


def _strength_bonus(strength: int, move_type: str, has_strength_mastery: bool) -> int:
    mt = normalize_attack_type(str(move_type or "normal"))
    if strength > 100:
        if mt == "normal":
            return 20
        if mt == "ultimate":
            return 50
        if mt in {"special", "unique_skill", "unique_path"}:
            return 30
        return 0
    if has_strength_mastery:
        if mt == "normal":
            return 10
        if mt == "ultimate":
            return 30
        if mt in {"special", "unique_skill", "unique_path"}:
            return 15
    return 0


def calculate_stat_damage(attacker: dict[str, Any], defender: dict[str, Any], move_type: str) -> tuple[int, dict[str, Any]]:
    att_typing = normalize_typing(attacker.get("typing", []))
    def_typing = normalize_typing(defender.get("typing", []))
    att_iq_eff = int(attacker.get("iq", 0)) + (MASTERMIND_IQ_BONUS if has_mastermind(att_typing) else 0)
    def_iq_eff = int(defender.get("iq", 0)) + (MASTERMIND_IQ_BONUS if has_mastermind(def_typing) else 0)
    att_biq = int(attacker.get("biq", 0)) + (MASTERMIND_BIQ_BONUS if has_mastermind(att_typing) else 0)
    def_biq = int(defender.get("biq", 0)) + (MASTERMIND_BIQ_BONUS if has_mastermind(def_typing) else 0)
    detail: dict[str, Any] = {"miss": False, "move_type": normalize_attack_type(move_type)}
    detail["attacker_typing"] = att_typing
    detail["defender_typing"] = def_typing
    if att_biq < def_biq:
        miss_chance = max(0, min(100, def_biq - att_biq))
        roll = random.randint(1, 100)
        detail["miss_chance"] = miss_chance
        detail["miss_roll"] = roll
        if roll <= miss_chance:
            detail["miss"] = True
            detail["final_damage"] = 0
            return 0, detail

    strength = int(attacker.get("strength", 0))
    x = strength / 2.0
    mt = normalize_attack_type(move_type)
    if mt == "normal":
        # Normal: moderate damage based on strength
        lo, hi = int(round(x - 5)), int(round(x + 5))
    elif mt == "special":
        # Special: noticeably stronger than normal
        lo, hi = int(round(x + 20)), int(round(x + 45))
    elif mt == "ultimate":
        # Ultimate: devastating, 3-4x strength scaling
        lo, hi = int(round(3 * x)), int(round(4 * x))
    elif mt in {"unique_skill", "unique_path"}:
        # Unique moves: between special and ultimate power
        lo, hi = int(round(x + 40)), int(round(x + 80))
    else:
        lo, hi = int(round(x - 5)), int(round(x + 5))
    if lo > hi:
        lo, hi = hi, lo
    rolled = random.randint(lo, hi)
    damage = max(1, rolled)
    detail["base_roll"] = damage

    mastery = attacker.get("mastery", [])
    has_strength_mastery = False
    if isinstance(mastery, list):
        has_strength_mastery = any(str(m).lower() == "strength" for m in mastery)
    bonus = _strength_bonus(strength, mt, has_strength_mastery)
    damage += bonus
    detail["strength_bonus"] = bonus

    tec_mult = _get_technique_bonus_multiplier(int(attacker.get("technique", 0)), mt)
    damage = float(damage) * tec_mult
    detail["technique_mult"] = tec_mult

    iq_bonus = float(att_iq_eff) / 5.0
    damage *= (1 + iq_bonus / 100.0)
    detail["attacker_iq_bonus_pct"] = iq_bonus

    def_iq_bonus = float(def_iq_eff) / 5.0
    damage *= (1 - def_iq_bonus / 100.0)
    detail["defender_iq_reduce_pct"] = def_iq_bonus

    type_mult = type_multiplier(att_typing, def_typing)
    def_mult = defensive_multiplier(att_typing, def_typing)
    damage *= type_mult * def_mult
    detail["typing_mult"] = type_mult
    detail["typing_defensive_mult"] = def_mult

    out = max(0, int(round(damage)))
    detail["final_damage"] = out
    return out, detail


def create_battle_state(
    data: dict[str, Any],
    battle_type: str,
    player_a_id: str,
    player_b_id: str,
    team_a: list[str],
    team_b: list[str],
    now: int,
    participant_a: dict[str, Any] | None = None,
    participant_b: dict[str, Any] | None = None,
) -> str:
    battle_id = str(uuid.uuid4())

    battle = data.setdefault("battle", {})
    active = battle.setdefault("active", {})
    active_by_user = battle.setdefault("active_by_user", {})

    a_id = str(player_a_id)
    b_id = str(player_b_id)
    p_a = _build_player_side(data, a_id, [str(x) for x in team_a])

    if isinstance(participant_b, dict) and bool(participant_b.get("cpu", False)):
        cpu_trophies = int(participant_b.get("trophies", 0)) if isinstance(participant_b, dict) else 0
        p_b = _build_cpu_side(data, team_size=len(team_b), min_rarity="Epic", player_trophies=cpu_trophies)
        p_b["cpu_meta"] = participant_b
    else:
        p_b = _build_player_side(data, b_id, [str(x) for x in team_b])

    state = {
        "battle_id": battle_id,
        "type": str(battle_type),
        "players": {a_id: p_a, b_id: p_b},
        "turn_user_id": a_id,
        "round": 1,
        "log": [],
        "ended": False,
        "winner_id": "",
        "created_at": int(now),
        "turn_started_at": int(now),
        "pending_defense_by_char_uid": {},
        "used_defenses_by_char_uid": {},
        "used_unique_skills_by_char_uid": {},
        "used_unique_path_by_char_uid": {},
        "last_move_group_by_char_uid": {},
        "last_move_group_by_side": {},
        "guard_broken_by_char_uid": {},
        "used_ultimate_count_by_side": {},
        "used_ultimate_by_char_uid": {},
    }

    active[battle_id] = state
    active_by_user[a_id] = battle_id
    if not bool(p_b.get("is_cpu", False)):
        active_by_user[b_id] = battle_id
    return battle_id


def _validate_battle_context(state: dict, actor_id: str) -> tuple[dict | None, dict | None, dict | None, str, str, str, str]:
    """Validate battle state, turn, players, and active fighters.

    Returns (None, me, opp, enemy_id, actor, my_uid, opp_uid) on success.
    Returns (error_dict, ...) on failure — first element is the error result.
    """
    if not isinstance(state, dict):
        return {"ok": False, "success": False, "error": "battle_not_found"}, None, None, "", "", "", ""
    if bool(state.get("ended", False)):
        return {"ok": False, "success": False, "error": "battle_not_active"}, None, None, "", "", "", ""

    actor = str(actor_id)
    if str(state.get("turn_user_id", "")) != actor:
        return {"ok": False, "success": False, "error": "not_your_turn"}, None, None, "", "", "", ""

    players = state.get("players", {}) if isinstance(state.get("players"), dict) else {}
    me = players.get(actor)
    enemy_id = next((str(pid) for pid in players.keys() if str(pid) != actor), "")
    opp = players.get(enemy_id)
    if not isinstance(me, dict) or not isinstance(opp, dict):
        return {"ok": False, "success": False, "error": "invalid_participants"}, None, None, "", "", "", ""

    my_team = me.get("team_uids", []) if isinstance(me.get("team_uids"), list) else []
    opp_team = opp.get("team_uids", []) if isinstance(opp.get("team_uids"), list) else []
    my_idx = int(me.get("current_index", 0))
    opp_idx = int(opp.get("current_index", 0))
    if my_idx < 0 or opp_idx < 0 or my_idx >= len(my_team) or opp_idx >= len(opp_team):
        return {"ok": False, "success": False, "error": "no_active_fighter"}, None, None, "", "", "", ""

    my_uid = str(my_team[my_idx])
    opp_uid = str(opp_team[opp_idx])
    return None, me, opp, enemy_id, actor, my_uid, opp_uid


def _handle_switch(state: dict, me: dict, enemy_id: str, my_team: list, my_uid: str, target_uid: str) -> dict:
    """Execute a fighter switch. Returns result dict."""
    if target_uid not in my_team:
        return {"ok": False, "success": False, "error": "invalid_switch"}
    if target_uid == my_uid:
        return {"ok": False, "success": False, "error": "already_active"}
    if int((me.get("hp", {}) or {}).get(target_uid, 0)) <= 0:
        return {"ok": False, "success": False, "error": "fighter_fainted"}

    me["current_index"] = my_team.index(target_uid)
    me["active_index"] = my_team.index(target_uid)
    state.setdefault("last_move_group_by_char_uid", {})[my_uid] = "normal_or_defensive"
    state.setdefault("last_move_group_by_side", {})[enemy_id] = "normal_or_defensive"
    state["turn_user_id"] = enemy_id
    state["turn_started_at"] = now_ts()
    state["round"] = int(state.get("round", 1)) + 1
    return {"ok": True, "success": True}


def _handle_defense_pending(state: dict, me: dict, my_uid: str, move_norm: str, actor: str) -> dict:
    """Record a pending defense move. Returns result dict."""
    used_defs = _safe_set_map(state, "used_defenses_by_char_uid", my_uid)
    if move_norm in used_defs:
        return {"ok": False, "success": False, "error": "defense_already_used"}
    used_defs.add(move_norm)
    pending = state.setdefault("pending_defense_by_char_uid", {})
    if not isinstance(pending, dict):
        pending = {}
        state["pending_defense_by_char_uid"] = pending
    pending[my_uid] = move_norm
    state.setdefault("last_move_group_by_char_uid", {})[my_uid] = "normal_or_defensive"
    state.setdefault("last_move_group_by_side", {})[actor] = "normal_or_defensive"
    state.setdefault("log", []).append(f"{actor} prepares {move_norm.upper()}")
    return {"ok": True, "success": True}


def _enforce_attack_usage_rules(state: dict, me: dict, my_uid: str, actor: str, move_norm: str, attack_key: str, my_team: list) -> str | None:
    """Check unique skill, unique path, ultimate usage rules.
    Returns error string or None if allowed.
    Also updates usage counters in state.
    """
    group = _move_group(move_norm)
    side_groups = state.setdefault("last_move_group_by_side", {})
    if not isinstance(side_groups, dict):
        side_groups = {}
        state["last_move_group_by_side"] = side_groups
    last_group = side_groups.get(actor)
    if last_group == "special_like" and group == "special_like":
        return "must_use_normal_or_defensive_first"

    if move_norm == "unique_skill":
        used_skills = _safe_set_map(state, "used_unique_skills_by_char_uid", my_uid)
        if attack_key in used_skills:
            return "unique_skill_already_used"
        used_skills.add(attack_key)

    if move_norm == "unique_path":
        used_path = state.setdefault("used_unique_path_by_char_uid", {})
        if not isinstance(used_path, dict):
            used_path = {}
            state["used_unique_path_by_char_uid"] = used_path
        if bool(used_path.get(my_uid, False)):
            return "unique_path_already_used"
        used_path[my_uid] = True

    if move_norm == "ultimate":
        used_ult = state.setdefault("used_ultimate_count_by_side", {})
        if not isinstance(used_ult, dict):
            used_ult = {}
            state["used_ultimate_count_by_side"] = used_ult
        used_ult_by_char = state.setdefault("used_ultimate_by_char_uid", {})
        if not isinstance(used_ult_by_char, dict):
            used_ult_by_char = {}
            state["used_ultimate_by_char_uid"] = used_ult_by_char
        if bool(used_ult_by_char.get(my_uid, False)):
            return "ultimate_already_used_by_fighter"
        team_limit = _ultimate_limit_for_team(len(my_team))
        spent = int(used_ult.get(actor, 0))
        if spent >= team_limit:
            return "ultimate_limit_reached"
        used_ult[actor] = spent + 1
        used_ult_by_char[my_uid] = True

    return None  # allowed


def _compute_attack_damage(data: dict, me: dict, opp: dict, my_uid: str, opp_uid: str, move_norm: str, attack_key: str) -> tuple[int, str]:
    """Calculate raw damage for an attack move, applying defense resolution.
    Returns (final_damage, group_string).
    """
    ensure_attacks_structure(data)
    attack_catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
    entry = attack_catalog.get(attack_key) if isinstance(attack_catalog, dict) else None

    mnorm = move_norm
    custom_power: int | None = None
    if isinstance(entry, dict):
        mnorm = normalize_attack_type(str(entry.get("type", mnorm)))
        p = entry.get("power")
        if isinstance(p, int):
            custom_power = int(p)
        elif isinstance(p, str) and p.strip().lstrip("-").isdigit():
            custom_power = int(p.strip())

    atk = (me.get("stats", {}) or {}).get(my_uid, {}) if isinstance(me.get("stats", {}), dict) else {}
    dfs = (opp.get("stats", {}) or {}).get(opp_uid, {}) if isinstance(opp.get("stats", {}), dict) else {}
    mastery_by_uid = me.get("mastery_by_uid", {}) if isinstance(me.get("mastery_by_uid"), dict) else {}
    atk = dict(atk) if isinstance(atk, dict) else {}
    atk["mastery"] = mastery_by_uid.get(my_uid, []) if isinstance(mastery_by_uid.get(my_uid, []), list) else []

    if custom_power is not None:
        damage = max(0, int(custom_power))
    else:
        damage, _ = calculate_stat_damage(atk, dfs, mnorm)

    # Check Card of the Day buff
    fighter_name = me.get("fighter_names", {}).get(my_uid, "") if isinstance(me.get("fighter_names"), dict) else ""
    cotd = data.get("cotd", {})
    if fighter_name and cotd.get("card_name") == fighter_name:
        damage = int(damage * 1.15)

    pending = me.get("pending_defense_by_char_uid", {}) if isinstance(me.get("pending_defense_by_char_uid"), dict) else {}
    # Actually pending is on state keyed by opp_uid — re-read from state
    return damage, _move_group(mnorm)


def _apply_defense_and_finalize_damage(state: dict, me: dict, opp: dict, my_uid: str, opp_uid: str, damage: int) -> int:
    """Resolve any pending defense against this attack and return final damage."""
    pending = state.setdefault("pending_defense_by_char_uid", {})
    pending_move = pending.pop(opp_uid, None) if isinstance(pending, dict) else None

    atk_stats = (me.get("stats", {}) or {}).get(my_uid, {}) if isinstance(me.get("stats", {}), dict) else {}
    def_stats = (opp.get("stats", {}) or {}).get(opp_uid, {}) if isinstance(opp.get("stats", {}), dict) else {}

    atk_str = int(atk_stats.get("strength", 0))
    def_end = int(def_stats.get("endurance", 0))
    def_spd = int(def_stats.get("speed", 0))
    def_tec = int(def_stats.get("technique", 0))
    atk_spd = int(atk_stats.get("speed", 0))

    if pending_move == "block":
        if atk_str - def_end >= REJECTION_THRESHOLD:
            state.setdefault("log", []).append("block_rejected")
        elif def_end > atk_str:
            me_hp = me.get("hp", {}) if isinstance(me.get("hp"), dict) else {}
            me_hp[my_uid] = max(0, int(me_hp.get(my_uid, 0)) - 20)
            me["hp"] = me_hp
            damage = 0
    elif pending_move == "dodge":
        if atk_spd - def_spd >= REJECTION_THRESHOLD:
            state.setdefault("log", []).append("dodge_rejected")
        elif def_spd > atk_spd:
            damage = 0
    elif pending_move == "revert":
        if atk_str - def_tec >= REJECTION_THRESHOLD:
            state.setdefault("log", []).append("revert_rejected")
        elif def_tec > atk_str:
            me_hp = me.get("hp", {}) if isinstance(me.get("hp"), dict) else {}
            me_hp[my_uid] = max(0, int(me_hp.get(my_uid, 0)) - max(0, damage))
            me["hp"] = me_hp
            damage = 0
    elif pending_move == "parry":
        if atk_str - def_end >= REJECTION_THRESHOLD:
            state.setdefault("log", []).append("parry_rejected")
        else:
            damage = 0
            gb = state.setdefault("guard_broken_by_char_uid", {})
            if isinstance(gb, dict):
                gb[my_uid] = True
    elif pending_move == "tank":
        reduction = def_end / max(1, def_end + atk_str)
        damage = max(0, int(round(damage * (1.0 - reduction))))

    return damage


def _apply_damage_and_check_elim(
    data: dict, state: dict, me: dict, opp: dict, opp_uid: str, damage: int,
    actor: str, enemy_id: str, move_norm: str, group: str, battle_id: str,
    my_uid: str,
) -> dict:
    """Apply damage to opponent, check elimination, possibly end battle.
    Returns result dict (may be end_battle).
    Also increments turn/round.
    """
    # Guard break: +50% damage if defender's guard was broken
    gb_map = state.setdefault("guard_broken_by_char_uid", {})
    if isinstance(gb_map, dict) and bool(gb_map.get(opp_uid, False)):
        damage = int(round(damage * 1.5))
        gb_map[opp_uid] = False

    # Apply HP
    opp_hp = opp.get("hp", {}) if isinstance(opp.get("hp", {}), dict) else {}
    new_hp = max(0, int(opp_hp.get(opp_uid, 0)) - max(0, int(damage)))
    opp_hp[opp_uid] = new_hp

    # Sync active fighters
    my_status = _sync_active_fighter(me)
    opp_status = _sync_active_fighter(opp)

    my_eliminated = my_status == "side_eliminated"
    opp_eliminated = opp_status == "side_eliminated"

    if my_eliminated and opp_eliminated:
        return end_battle(data, battle_id, actor, enemy_id, "draw")
    if opp_status == "side_eliminated":
        return end_battle(data, battle_id, actor, enemy_id, "all_fainted")
    if my_status == "side_eliminated":
        return end_battle(data, battle_id, enemy_id, actor, "all_fainted")

    # Log + update state
    state.setdefault("last_move_group_by_char_uid", {})[my_uid] = group if me.get("team_uids") else group
    state.setdefault("last_move_group_by_side", {})[actor] = group
    state.setdefault("log", []).append(f"{actor}:{move_norm}:{damage}")

    # Pass turn
    state["turn_user_id"] = enemy_id
    state["turn_started_at"] = now_ts()
    state["round"] = int(state.get("round", 1)) + 1
    return {"ok": True, "success": True}


def apply_move(data: dict[str, Any], battle_id: str, actor_id: str, move_type: str, value: Any) -> dict[str, Any]:
    """Process a battle move: switch, defense, or attack."""
    # ── 1. Validate context ────────────────────────────────────────
    battle_root = data.get("battle", {})
    active = battle_root.get("active", {}) if isinstance(battle_root, dict) else {}
    state = active.get(str(battle_id)) if isinstance(active, dict) else None

    err, me, opp, enemy_id, actor, my_uid, opp_uid = _validate_battle_context(state, actor_id)
    if err is not None:
        return err

    my_team = me.get("team_uids", []) if isinstance(me.get("team_uids"), list) else []

    # ── 2. Forfeit ─────────────────────────────────────────────────
    if str(move_type).lower() == "forfeit":
        return end_battle(data, battle_id, enemy_id, actor, "forfeit")

    # ── 3. Switch ──────────────────────────────────────────────────
    if str(move_type).lower() == "switch":
        return _handle_switch(state, me, enemy_id, my_team, my_uid, str(value or ""))

    # ── 4. Defense (record pending) ────────────────────────────────
    move_norm = normalize_attack_type(str(move_type or "normal"))
    if move_norm in {"block", "dodge", "revert", "parry", "tank"}:
        result = _handle_defense_pending(state, me, my_uid, move_norm, actor)
        if not result.get("ok"):
            return result
        # Pass turn after setting up defense
        state["turn_user_id"] = enemy_id
        state["turn_started_at"] = now_ts()
        state["round"] = int(state.get("round", 1)) + 1
        return {"ok": True, "success": True}

    # ── 5. Attack: enforce usage rules ─────────────────────────────
    attack_key = str(value or move_type)
    rule_error = _enforce_attack_usage_rules(state, me, my_uid, actor, move_norm, attack_key, my_team)
    if rule_error is not None:
        return {"ok": False, "success": False, "error": rule_error}

    # ── 6. Attack: compute damage ──────────────────────────────────
    damage, group = _compute_attack_damage(data, me, opp, my_uid, opp_uid, move_norm, attack_key)

    # ── 7. Attack: resolve defense ─────────────────────────────────
    damage = _apply_defense_and_finalize_damage(state, me, opp, my_uid, opp_uid, damage)

    # ── 8. Attack: apply damage + check elimination ────────────────
    return _apply_damage_and_check_elim(
        data, state, me, opp, opp_uid, damage,
        actor, enemy_id, move_norm, group, battle_id,
        my_uid,
    )


def _pvp_trophy_delta(tp_a: int, tp_b: int, winner: str) -> tuple[int, int]:
    """
    Calculate PvP trophy changes based on spec.
    A = higher trophies, B = lower trophies (or equal within 50).
    Returns (delta_a, delta_b) — positive = gain, negative = loss.
    winner: "A", "B", or "draw"
    """
    diff = abs(tp_a - tp_b)
    same = diff <= 50  # treat as equal if within 50

    if same:
        if winner == "draw":
            return 10, 10
        gain = random.randint(25, 40)
        if winner == "A":
            return gain, -gain
        else:
            return -gain, gain
    else:
        # A has higher trophies, B has lower
        if winner == "draw":
            # B loses 0-10, A gains 10-20
            b_loss = random.randint(0, 10)
            a_gain = random.randint(10, 20)
            return a_gain, -b_loss
        elif winner == "B":
            gain = random.randint(30, 50)
            return -gain, gain
        else:  # A wins
            gain = random.randint(20, 30)
            return gain, -gain


def _elo_delta_cpu(tp: int, tc: int, won: bool) -> int:
    """Legacy ELO delta for CPU matches only."""
    ew = 1 / (1 + 10 ** ((tc - tp) / 400))
    k = 22
    if tp < 500:
        k = 28
    elif tp > 2000:
        k = 16
    raw = round(k * ((1 - ew) if won else (0 - ew)))
    if won:
        return max(4, min(22, raw))
    return max(-22, min(-4, raw))


def _update_mission_progress(data: dict, user_id: str, battle_type: str, won: bool) -> None:
    """Track mission progress for season missions."""
    try:
        season = data.get("season", {})
        if not isinstance(season, dict) or not season.get("active"):
            return
        snum     = str(season.get("current_season", 1))
        missions = season.get("missions", {}) or {}
        player   = data.get("players", {}).get(str(user_id), {})
        user     = player.get("user", {}) if isinstance(player, dict) else {}
        if not isinstance(user, dict):
            return
        mp = user.setdefault("mission_progress", {}).setdefault(snum, {})
        for mid, m in missions.items():
            if not isinstance(m, dict):
                continue
            req = str(m.get("requirement", ""))
            if req == "battles_played":
                mp[mid] = int(mp.get(mid, 0)) + 1
            elif req == "ranked_wins" and won and battle_type == "ranked":
                mp[mid] = int(mp.get(mid, 0)) + 1
            elif req == "tournament_wins" and won and battle_type == "tournament":
                mp[mid] = int(mp.get(mid, 0)) + 1
    except Exception:
        logger.exception("Failed to update mission progress for user %s", user_id)


WIN_COIN_REWARD_MIN = 50
WIN_COIN_REWARD_MAX = 90


def _resolve_cpu_outcome(state: dict, data: dict, human_id: str, winner_id: str) -> None:
    """Apply CPU match ELO, anti-farm scaling, coin reward, and opponent line."""
    human = get_player(data, human_id)
    user_data = human.get("user", {}) if isinstance(human, dict) else {}
    tp = int(user_data.get("trophies", 0))

    players = state.get("players", {}) if isinstance(state.get("players"), dict) else {}
    cpu_id = next((str(pid) for pid, ps in players.items() if isinstance(ps, dict) and bool(ps.get("is_cpu", False))), "")
    cpu_meta = (players.get(cpu_id, {}) or {}).get("cpu_meta", {}) if isinstance(players.get(cpu_id, {}), dict) else {}
    tc = int(cpu_meta.get("trophies", tp)) if isinstance(cpu_meta, dict) else tp

    won = str(winner_id) == human_id
    delta = _elo_delta_cpu(tp, tc, won)

    # Anti-farm: scale down if many CPU wins in last 10 minutes
    now = int(state.get("turn_started_at", 0))
    cpu_wins = user_data.setdefault("cpu_win_timestamps", [])
    if isinstance(cpu_wins, list):
        cpu_wins[:] = [ts for ts in cpu_wins if now - ts <= 600]
        recent_wins = len(cpu_wins)
    else:
        recent_wins = 0
        user_data["cpu_win_timestamps"] = []
        cpu_wins = user_data["cpu_win_timestamps"]

    if won:
        cpu_wins.append(now)
        if recent_wins >= 6:
            delta = max(1, round(delta * 0.25))
        elif recent_wins >= 3:
            delta = max(1, round(delta * 0.5))

    # Daily +100 trophy cap from CPU wins (UTC-midnight rollover).
    day_start = (int(now) // 86400) * 86400
    if int(user_data.get("last_cpu_trophy_reset", 0)) < day_start:
        user_data["daily_cpu_trophy_sum"] = 0
        user_data["last_cpu_trophy_reset"] = day_start
    if won and delta > 0:
        sum_today = int(user_data.get("daily_cpu_trophy_sum", 0))
        if sum_today >= 100:
            delta = 0
        elif sum_today + delta > 100:
            delta = 100 - sum_today
        user_data["daily_cpu_trophy_sum"] = sum_today + delta

    user_data["trophies"] = max(0, tp + delta)
    user_data["rank"] = _rank_from_trophies(int(user_data.get("trophies", 0)))
    state["cpu_trophy_change"] = delta

    if won:
        coin_reward = random.randint(WIN_COIN_REWARD_MIN, WIN_COIN_REWARD_MAX)
        user_data["balance"] = int(user_data.get("balance", user_data.get("coins", 0))) + coin_reward
        state["coin_reward"] = coin_reward

    display_name = str(cpu_meta.get("display_name", "🤖 CPU")) if isinstance(cpu_meta, dict) else "🤖 CPU"
    personality = str(cpu_meta.get("personality", "Balanced")) if isinstance(cpu_meta, dict) else "Balanced"
    state["cpu_opponent_line"] = f"Opponent: {display_name} ({tc} trophies, Personality: {personality})"


def _resolve_pvp_outcome(state: dict, data: dict, players: dict, winner_id: str, reason: str, no_contest: bool) -> bool:
    """Apply PvP trophy deltas and coin reward. Returns True if draw."""
    pid_list = list(players.keys())
    if len(pid_list) != 2:
        return False

    pid_a, pid_b = str(pid_list[0]), str(pid_list[1])
    player_a = get_player(data, pid_a)
    player_b = get_player(data, pid_b)
    ud_a = player_a.get("user", {}) if isinstance(player_a, dict) else {}
    ud_b = player_b.get("user", {}) if isinstance(player_b, dict) else {}
    tp_a = int(ud_a.get("trophies", 0))
    tp_b = int(ud_b.get("trophies", 0))

    if tp_a >= tp_b:
        high_pid, low_pid = pid_a, pid_b
        high_ud, low_ud = ud_a, ud_b
        high_tp, low_tp = tp_a, tp_b
    else:
        high_pid, low_pid = pid_b, pid_a
        high_ud, low_ud = ud_b, ud_a
        high_tp, low_tp = tp_b, tp_a

    is_draw = (reason == "draw")
    if is_draw:
        winner_label = "draw"
    elif str(winner_id) == high_pid:
        winner_label = "A"
    else:
        winner_label = "B"

    delta_high, delta_low = _pvp_trophy_delta(high_tp, low_tp, winner_label)
    high_ud["trophies"] = max(0, high_tp + delta_high)
    low_ud["trophies"] = max(0, low_tp + delta_low)
    high_ud["rank"] = _rank_from_trophies(int(high_ud.get("trophies", 0)))
    low_ud["rank"] = _rank_from_trophies(int(low_ud.get("trophies", 0)))

    state["pvp_trophy_changes"] = {high_pid: delta_high, low_pid: delta_low}

    if not is_draw and winner_id in (high_pid, low_pid):
        winner_ud = high_ud if winner_id == high_pid else low_ud
        coin_reward = random.randint(WIN_COIN_REWARD_MIN, WIN_COIN_REWARD_MAX)
        winner_ud["balance"] = int(winner_ud.get("balance", winner_ud.get("coins", 0))) + coin_reward
        state["coin_reward"] = coin_reward

    return is_draw


def _grant_battle_rewards(data: dict, state: dict, winner_id: str, loser_id: str, battle_type: str, is_draw: bool, no_contest: bool) -> None:
    """Grant XP, CP, tournament XP, and update season missions after battle."""
    from bot.utils.xp_logic import grant_battle_xp_cp
    from bot.utils.pack_logic import grant_pending_milestone_packs

    if not is_draw and not no_contest:
        w_xp, w_cp = grant_battle_xp_cp(data, winner_id, f"{battle_type}_win")
        l_xp, l_cp = grant_battle_xp_cp(data, loser_id,  f"{battle_type}_loss")
        state["winner_xp"] = w_xp
        state["loser_xp"]  = l_xp
        state["winner_cp"] = w_cp
        state["loser_cp"]  = l_cp

        # Grant pending milestone packs for both players
        w_packs = grant_pending_milestone_packs(data, winner_id)
        l_packs = grant_pending_milestone_packs(data, loser_id)
        if w_packs:
            state["winner_milestone_packs"] = w_packs
        if l_packs:
            state["loser_milestone_packs"] = l_packs
    elif is_draw:
        for pid in [winner_id, loser_id]:
            grant_battle_xp_cp(data, pid, f"{battle_type}_loss")
            packs = grant_pending_milestone_packs(data, pid)
            if packs:
                state[f"{pid}_milestone_packs"] = packs

    # Tournament XP
    if battle_type == "tournament" and not is_draw and not no_contest:
        t = data.get("tournament", {})
        if isinstance(t, dict) and t.get("active"):
            parts = t.setdefault("participants", {})
            if winner_id in parts and isinstance(parts[winner_id], dict):
                parts[winner_id]["xp_earned"] = int(parts[winner_id].get("xp_earned", 0)) + 250

    # Season missions
    if not no_contest:
        for pid, won in [(winner_id, True), (loser_id, False)]:
            _update_mission_progress(data, pid, battle_type, won)


_RANK_ACHIEVEMENT: dict[str, str] = {
    "Silver":  "reach_silver",
    "Gold":    "reach_gold",
    "Diamond": "reach_diamond",
    "Ruby":    "reach_ruby",
}


def _update_ranked_stats_and_achievements(data: dict[str, Any], state: dict[str, Any], winner_id: str, loser_id: str, battle_type: str, is_draw: bool, no_contest: bool) -> None:
    """Update ranked_stats wins/losses/streak and fire achievement checks."""
    if battle_type != "ranked" or no_contest:
        return

    players = state.get("players", {}) if isinstance(state.get("players"), dict) else {}

    for pid in list(players.keys()):
        is_cpu = bool(players.get(pid, {}).get("is_cpu", False)) if isinstance(players.get(pid), dict) else False
        if is_cpu:
            continue
        player = get_player(data, str(pid))
        if not isinstance(player, dict):
            continue
        ranked = player.setdefault("ranked_stats", {"wins": 0, "losses": 0, "streak": 0, "last_10": []})
        if not isinstance(ranked, dict):
            ranked = {"wins": 0, "losses": 0, "streak": 0, "last_10": []}
            player["ranked_stats"] = ranked

        won = (not is_draw) and (str(pid) == str(winner_id))
        lost = (not is_draw) and (str(pid) == str(loser_id))

        if won:
            ranked["wins"] = int(ranked.get("wins", 0)) + 1
            ranked["streak"] = int(ranked.get("streak", 0)) + 1
        elif lost:
            ranked["losses"] = int(ranked.get("losses", 0)) + 1
            ranked["streak"] = 0

        last_10 = ranked.get("last_10", [])
        if not isinstance(last_10, list):
            last_10 = []
        last_10.append("W" if won else ("L" if lost else "D"))
        ranked["last_10"] = last_10[-10:]

        # Achievement checks
        wins = int(ranked.get("wins", 0))
        streak = int(ranked.get("streak", 0))

        if won:
            for ach_id, threshold in (("first_blood", 1), ("win_10_battles", 10), ("win_50_battles", 50), ("win_100_battles", 100)):
                if wins == threshold:
                    _ach.grant(data, player, ach_id)
            if streak >= 5:
                _ach.grant(data, player, "win_streak_5")

        # Rank-up achievements — check current rank vs previous
        user_data = player.get("user", {}) if isinstance(player, dict) else {}
        new_rank = str(user_data.get("rank", "Copper")) if isinstance(user_data, dict) else "Copper"
        ach_id = _RANK_ACHIEVEMENT.get(new_rank)
        if ach_id:
            _ach.grant(data, player, ach_id)

    # Battle-move stat achievements (ultimates + successful blocks)
    for pid in list(players.keys()):
        is_cpu = bool(players.get(pid, {}).get("is_cpu", False)) if isinstance(players.get(pid), dict) else False
        if is_cpu:
            continue
        player = get_player(data, str(pid))
        if not isinstance(player, dict):
            continue
        user_data = player.get("user", {}) if isinstance(player, dict) else {}
        if not isinstance(user_data, dict):
            continue

        # Count ultimates used by this player this battle
        used_ult_count = state.get("used_ultimate_count_by_side", {})
        if isinstance(used_ult_count, dict):
            ult_this_battle = int(used_ult_count.get(str(pid), 0))
            if ult_this_battle > 0:
                prev = int(user_data.get("total_ultimates_landed", 0))
                user_data["total_ultimates_landed"] = prev + ult_this_battle
                if user_data["total_ultimates_landed"] >= 10:
                    _ach.grant(data, player, "land_10_ultimates")

        # Count successful blocks by this player: blocks that weren't rejected
        # We track via used_defenses_by_char_uid — count 'block' entries for player's chars
        my_side = players.get(str(pid))
        if isinstance(my_side, dict):
            my_team = my_side.get("team_uids", []) if isinstance(my_side.get("team_uids"), list) else []
            blocks_this_battle = 0
            used_defs = state.get("used_defenses_by_char_uid", {}) if isinstance(state.get("used_defenses_by_char_uid"), dict) else {}
            log = state.get("log", []) if isinstance(state.get("log"), list) else []
            rejected_blocks = sum(1 for entry in log if str(entry) == "block_rejected")
            for uid in my_team:
                defs = used_defs.get(str(uid))
                if isinstance(defs, (set, list)) and "block" in defs:
                    blocks_this_battle += 1
            successful_blocks = max(0, blocks_this_battle - rejected_blocks)
            if successful_blocks > 0:
                prev_blocks = int(user_data.get("total_blocks_landed", 0))
                user_data["total_blocks_landed"] = prev_blocks + successful_blocks
                if user_data["total_blocks_landed"] >= 10:
                    _ach.grant(data, player, "perfect_block_10")


def end_battle(data: dict[str, Any], battle_id: str, winner_id: str, loser_id: str, reason: str) -> dict[str, Any]:
    """End a battle: validate state, award trophies/rewards, and mark complete."""
    battle = data.get("battle", {})
    if not isinstance(battle, dict):
        return {"ok": False, "success": False, "error": "battle_data_missing"}

    active = battle.get("active", {}) if isinstance(battle.get("active", {}), dict) else {}
    state = active.get(str(battle_id)) if isinstance(active, dict) else None
    if not isinstance(state, dict):
        return {"ok": False, "success": False, "error": "battle_not_found"}

    reason_key = str(reason)
    no_contest = reason_key in {"timeout_abandoned", "abandoned", "no_contest"}
    is_draw = (reason_key == "draw")

    # Mark ended + clean up active_by_user
    state["ended"] = True
    state["winner_id"] = "" if no_contest else str(winner_id)
    state["reason"] = reason_key

    active_by_user = battle.get("active_by_user", {}) if isinstance(battle.get("active_by_user", {}), dict) else {}
    for pid in list(state.get("players", {}).keys()):
        active_by_user.pop(str(pid), None)

    # Ranked trophy + coin resolution
    players = state.get("players", {}) if isinstance(state.get("players"), dict) else {}
    if str(state.get("type", "ranked")) == "ranked" and not no_contest:
        cpu_id = next((str(pid) for pid, ps in players.items() if isinstance(ps, dict) and bool(ps.get("is_cpu", False))), "")
        if cpu_id:
            human_id = next((str(pid) for pid in players.keys() if str(pid) != cpu_id), "")
            _resolve_cpu_outcome(state, data, human_id, winner_id)
            # Tutorial: track first win
            if str(winner_id) == human_id:
                winner_player = get_player(data, winner_id)
                winner_user = winner_player.get("user", {}) if isinstance(winner_player, dict) else {}
                if isinstance(winner_user, dict):
                    from bot.features.tutorial import advance_tutorial
                    advance_tutorial(winner_user, "win_battle")
        else:
            is_draw = _resolve_pvp_outcome(state, data, players, winner_id, reason, no_contest)

    # Rival tracking (only for ranked PvP, not CPU)
    players = state.get("players", {}) if isinstance(state.get("players"), dict) else {}
    cpu_id = next((str(pid) for pid, ps in players.items() if isinstance(ps, dict) and bool(ps.get("is_cpu", False))), "")
    if str(state.get("type", "ranked")) == "ranked" and not no_contest and not is_draw and not cpu_id:
        loser_player = get_player(data, loser_id)
        winner_player = get_player(data, winner_id)
        loser_user = loser_player.get("user", {}) if isinstance(loser_player, dict) else {}
        winner_user = winner_player.get("user", {}) if isinstance(winner_player, dict) else {}
        winner_name = str(winner_user.get("name", "Unknown")) if isinstance(winner_user, dict) else "Unknown"

        # Update loser's rival tracking
        if isinstance(loser_user, dict):
            rival = loser_user.setdefault("rival", {"rival_id": None, "rival_name": "", "losses_to": 0, "wins_vs": 0})
            if not isinstance(rival, dict):
                rival = {"rival_id": None, "rival_name": "", "losses_to": 0, "wins_vs": 0}
                loser_user["rival"] = rival
            if rival.get("rival_id") == winner_id:
                rival["losses_to"] = rival.get("losses_to", 0) + 1
            elif rival.get("losses_to", 0) == 0:
                rival["rival_id"] = winner_id
                rival["rival_name"] = winner_name
                rival["losses_to"] = 1

        # Update winner's rival tracking
        if isinstance(winner_user, dict):
            w_rival = winner_user.get("rival", {})
            if not isinstance(w_rival, dict):
                w_rival = {"rival_id": None, "rival_name": "", "losses_to": 0, "wins_vs": 0}
                winner_user["rival"] = w_rival
            if w_rival.get("rival_id") == loser_id:
                w_rival["wins_vs"] = w_rival.get("wins_vs", 0) + 1

        # Bounty tracking
        bounty = data.get("bounty", {}) if isinstance(data.get("bounty", {}), dict) else {}
        if bounty and bounty.get("target_id") == loser_id:
            winner_user["balance"] = winner_user.get("balance", 0) + bounty.get("reward", 3000)
            state["bounty_claimed"] = True
            state["bounty_claimer"] = winner_name
            data["bounty"] = {}

    # XP, CP, tournament, missions
    battle_type = str(state.get("type", "ranked"))
    _grant_battle_rewards(data, state, winner_id, loser_id, battle_type, is_draw, no_contest)

    # Ranked stats + achievement triggers
    _update_ranked_stats_and_achievements(data, state, winner_id, loser_id, battle_type, is_draw, no_contest)

    return {
        "ok": True, "success": True, "battle_over": True,
        "winner_id": "" if no_contest else str(winner_id),
        "loser_id": "" if no_contest else str(loser_id),
        "reason": reason_key,
    }
