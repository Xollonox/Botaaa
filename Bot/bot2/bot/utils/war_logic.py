"""Gang War logic — matchmaking, points, rewards."""
from __future__ import annotations
import os
import uuid
from typing import Any
from bot.utils.timeutil import now_ts

# ── Constants ─────────────────────────────────────────────────────
WAR_FORMATS          = [2, 10, 20, 30]
MAX_TROPHY_DIFF      = 100
PREP_DURATION        = int(os.getenv("GANG_WAR_PREP_SECONDS",   "86400"))
BATTLE_DURATION      = int(os.getenv("GANG_WAR_BATTLE_SECONDS", "86400"))
QUEUE_TIMEOUT        = 86400   # 24h
WAR_COOLDOWN         = 172800  # 48h after leaving gang

WIN_COINS  = {2: 500,   10: 1000,  20: 3000,  30: 5000}
LOSS_COINS = {2: 250,   10: 500,   20: 1500,  30: 2500}
WIN_PACKS  = 3
LOSS_PACKS = 1


# ── Data helpers ──────────────────────────────────────────────────

def _war_root(data: dict[str, Any]) -> dict[str, Any]:
    w = data.setdefault("gang_wars", {})
    w.setdefault("active_wars", {})
    w.setdefault("queue", {})
    return w


def get_player_war_pref(data: dict[str, Any], uid: str) -> str:
    p = data.get("players", {}).get(str(uid), {})
    u = p.get("user", {}) if isinstance(p, dict) else {}
    return str(u.get("war_preference", "in")).lower()


def get_war_defense_squad(data: dict[str, Any], uid: str) -> list[str]:
    p = data.get("players", {}).get(str(uid), {})
    u = p.get("user", {}) if isinstance(p, dict) else {}
    sq = u.get("war_defense_squad", [])
    return list(sq) if isinstance(sq, list) else []


def set_war_defense_squad(data: dict[str, Any], uid: str, card_uids: list[str]) -> None:
    p = data.get("players", {}).get(str(uid), {})
    u = p.get("user", {}) if isinstance(p, dict) else {}
    if isinstance(u, dict):
        u["war_defense_squad"] = card_uids[:4]


def is_in_war_cooldown(data: dict[str, Any], uid: str) -> bool:
    p = data.get("players", {}).get(str(uid), {})
    u = p.get("user", {}) if isinstance(p, dict) else {}
    cd = int(u.get("war_cooldown_until", 0)) if isinstance(u, dict) else 0
    return now_ts() < cd


def set_war_cooldown(data: dict[str, Any], uid: str) -> None:
    p = data.get("players", {}).get(str(uid), {})
    u = p.get("user", {}) if isinstance(p, dict) else {}
    if isinstance(u, dict):
        u["war_cooldown_until"] = now_ts() + WAR_COOLDOWN


def get_user_active_war(data: dict[str, Any], uid: str) -> tuple[str | None, dict | None, str | None]:
    """Returns (war_id, war, gang_side 'a'/'b') or (None, None, None)."""
    w = _war_root(data)
    for wid, war in w.get("active_wars", {}).items():
        if not isinstance(war, dict): continue
        if uid in war.get("participants_a", []):
            return wid, war, "a"
        if uid in war.get("participants_b", []):
            return wid, war, "b"
    return None, None, None


def get_gang_active_war(data: dict[str, Any], gang_id: str) -> tuple[str | None, dict | None]:
    w = _war_root(data)
    for wid, war in w.get("active_wars", {}).items():
        if not isinstance(war, dict): continue
        if war.get("gang_a") == gang_id or war.get("gang_b") == gang_id:
            return wid, war
    return None, None


def avg_trophies(data: dict[str, Any], uids: list[str]) -> int:
    if not uids: return 0
    total = 0
    for uid in uids:
        p = data.get("players", {}).get(str(uid), {})
        u = p.get("user", {}) if isinstance(p, dict) else {}
        total += int(u.get("trophies", 0)) if isinstance(u, dict) else 0
    return total // len(uids)


# ── Queue ─────────────────────────────────────────────────────────

def queue_war(data: dict[str, Any], gang_id: str, fmt: int, participants: list[str]) -> str:
    w = _war_root(data)
    qid = str(uuid.uuid4())[:8]
    w["queue"][qid] = {
        "gang_id":      gang_id,
        "format":       fmt,
        "participants": participants,
        "avg_trophies": avg_trophies(data, participants),
        "queued_at":    now_ts(),
    }
    return qid


def find_match(data: dict[str, Any], qid: str) -> str | None:
    """Find best matching queue entry. Returns opponent qid or None."""
    w  = _war_root(data)
    q  = w["queue"]
    me = q.get(qid)
    if not isinstance(me, dict): return None

    best_qid  = None
    best_diff = MAX_TROPHY_DIFF + 1

    for oqid, oq in q.items():
        if oqid == qid: continue
        if not isinstance(oq, dict): continue
        if oq.get("format") != me.get("format"): continue
        diff = abs(int(oq.get("avg_trophies", 0)) - int(me.get("avg_trophies", 0)))
        if diff < best_diff:
            best_diff = diff
            best_qid  = oqid

    return best_qid if best_diff <= MAX_TROPHY_DIFF else None


def create_war(data: dict[str, Any], qid_a: str, qid_b: str) -> str:
    w   = _war_root(data)
    q   = w["queue"]
    qa  = q[qid_a]
    qb  = q[qid_b]
    wid = str(uuid.uuid4())[:8]
    w["active_wars"][wid] = {
        "war_id":           wid,
        "format":           qa["format"],
        "phase":            "prep",
        "gang_a":           qa["gang_id"],
        "gang_b":           qb["gang_id"],
        "avg_trophies_a":   qa["avg_trophies"],
        "avg_trophies_b":   qb["avg_trophies"],
        "participants_a":   qa["participants"],
        "participants_b":   qb["participants"],
        "defense_squads":   {},
        "attacks":          {},
        "attacked_targets": [],
        "phase_started_at": now_ts(),
        "created_at":       now_ts(),
    }
    del q[qid_a]
    del q[qid_b]
    return wid


# ── Phase helpers ─────────────────────────────────────────────────

def check_phase_transition(data: dict[str, Any], wid: str) -> str | None:
    """Returns new phase if transition needed, else None."""
    w   = _war_root(data)
    war = w["active_wars"].get(wid)
    if not isinstance(war, dict): return None
    phase   = war.get("phase")
    fmt     = int(war.get("format", 10))
    elapsed = now_ts() - int(war.get("phase_started_at", 0))
    prep_dur   = 300 if fmt == 2 else PREP_DURATION
    battle_dur = 600 if fmt == 2 else BATTLE_DURATION
    if phase == "prep" and elapsed >= prep_dur:
        war["phase"]            = "battle"
        war["phase_started_at"] = now_ts()
        return "battle"
    if phase == "battle" and elapsed >= battle_dur:
        return "ended"
    return None


def is_battle_phase(war: dict[str, Any]) -> bool:
    return str(war.get("phase", "")) == "battle"


def is_prep_phase(war: dict[str, Any]) -> bool:
    return str(war.get("phase", "")) == "prep"


# ── Attack / Points ───────────────────────────────────────────────

def can_attack(war: dict[str, Any], attacker_uid: str, target_uid: str) -> tuple[bool, str]:
    if not is_battle_phase(war):
        return False, "War is not in battle phase."
    if attacker_uid in war.get("attacks", {}):
        return False, "You already used your attack."
    if target_uid in war.get("attacked_targets", []):
        return False, "That opponent has already been attacked by your team."
    return True, "ok"


def record_attack(
    data: dict[str, Any], wid: str,
    attacker_uid: str, target_uid: str,
    attacker_survivors: int, attacker_hp_pcts: list[float],
    defender_survivors: int, defender_hp_pcts: list[float],
    attacker_won: bool,
) -> None:
    w   = _war_root(data)
    war = w["active_wars"].get(wid)
    if not isinstance(war, dict): return

    if attacker_won:
        stars = attacker_survivors
        pct   = int(sum(attacker_hp_pcts) / max(1, len(attacker_hp_pcts)))
        def_stars = 0
        def_pct   = 0
    else:
        stars     = 0
        pct       = 0
        def_stars = defender_survivors
        def_pct   = int(sum(defender_hp_pcts) / max(1, len(defender_hp_pcts)))

    war.setdefault("attacks", {})[attacker_uid] = {
        "target_uid":      target_uid,
        "attacker_won":    attacker_won,
        "stars":           stars,
        "percent":         pct,
        "def_stars":       def_stars,
        "def_percent":     def_pct,
        "done":            True,
    }
    war.setdefault("attacked_targets", [])
    if target_uid not in war["attacked_targets"]:
        war["attacked_targets"].append(target_uid)


# ── Score ─────────────────────────────────────────────────────────

def compute_war_score(war: dict[str, Any], side: str) -> tuple[int, int]:
    """Returns (total_stars, total_percent) for a side."""
    participants = war.get(f"participants_{side}", [])
    opp_side     = "b" if side == "a" else "a"
    opp_parts    = war.get(f"participants_{opp_side}", [])
    attacks      = war.get("attacks", {})
    total_stars  = 0
    total_pct    = 0
    for uid in participants:
        atk = attacks.get(uid)
        if not isinstance(atk, dict): continue
        total_stars += int(atk.get("stars", 0))
        total_pct   += int(atk.get("percent", 0))
    # Also count defensive points from opponent attacks
    for uid in opp_parts:
        atk = attacks.get(uid)
        if not isinstance(atk, dict): continue
        target = atk.get("target_uid")
        if target in participants:
            total_stars += int(atk.get("def_stars", 0))
            total_pct   += int(atk.get("def_percent", 0))
    return total_stars, total_pct


def determine_winner(war: dict[str, Any]) -> str:
    """Returns 'a', 'b', or 'draw'."""
    sa, pa = compute_war_score(war, "a")
    sb, pb = compute_war_score(war, "b")
    if sa > sb: return "a"
    if sb > sa: return "b"
    if pa > pb: return "a"
    if pb > pa: return "b"
    return "draw"


# ── Rewards ───────────────────────────────────────────────────────

def grant_war_rewards(data: dict[str, Any], wid: str) -> None:
    w   = _war_root(data)
    war = w["active_wars"].get(wid)
    if not isinstance(war, dict): return

    winner_side = determine_winner(war)
    fmt         = int(war.get("format", 10))

    for side in ("a", "b"):
        is_winner    = (winner_side == side or winner_side == "draw")
        coins        = WIN_COINS.get(fmt, 1000) if is_winner else LOSS_COINS.get(fmt, 500)
        pack_qty     = WIN_PACKS if is_winner else LOSS_PACKS
        participants = war.get(f"participants_{side}", [])
        attacks      = war.get("attacks", {})

        for uid in participants:
            if uid not in attacks: continue  # didn't participate in battle
            p = data.get("players", {}).get(str(uid), {})
            u = p.get("user", {}) if isinstance(p, dict) else {}
            if not isinstance(u, dict): continue
            u["balance"] = int(u.get("balance", 0)) + coins
            # Grant war packs
            inv = u.setdefault("pack_inventory", [])
            for _ in range(pack_qty):
                inv.append({"key": "war_pack", "name": "War Pack", "source": "gang_war"})

    war["phase"]      = "ended"
    war["winner_side"] = winner_side
