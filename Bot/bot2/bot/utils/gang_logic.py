"""Gang management helpers."""

from __future__ import annotations

from typing import Any

from bot.utils.ui import e

MAX_MEMBERS = 20
GANG_CREATION_COST = 10_000

ROLE_ORDER  = ["head", "vice", "recruiter", "elder", "member"]
ROLE_ICONS  = {
    "head":      "👑",
    "vice":      "⚔️",
    "recruiter": "📣",
    "elder":     "🏅",
    "member":    "👤",
}
ROLE_LABELS = {
    "head":      "Head",
    "vice":      "Vice Head",
    "recruiter": "Recruiter",
    "elder":     "Elder",
    "member":    "Member",
}


def get_role(gang: dict[str, Any], user_id: str) -> str:
    if str(gang.get("leader_id", "")) == str(user_id):
        return "head"
    roles = gang.get("roles", {})
    if isinstance(roles, dict):
        return str(roles.get(str(user_id), "member"))
    return "member"


def get_role_label(gang: dict[str, Any], user_id: str) -> str:
    return ROLE_LABELS.get(get_role(gang, user_id), "Member")


def get_role_icon(gang: dict[str, Any], user_id: str, data: dict[str, Any] | None = None) -> str:
    role = get_role(gang, user_id)
    configured = e("vice_head" if role == "vice" else role, data)
    return configured if configured != "•" else ROLE_ICONS.get(role, "👤")


def is_head(gang: dict[str, Any], user_id: str) -> bool:
    return str(gang.get("leader_id", "")) == str(user_id)


def is_vice_or_above(gang: dict[str, Any], user_id: str) -> bool:
    return get_role(gang, user_id) in ("head", "vice")


def has_permission_invite(gang: dict[str, Any], user_id: str) -> bool:
    return get_role(gang, user_id) in ("head", "vice", "recruiter")


def can_kick(gang: dict[str, Any], actor_id: str, target_id: str) -> tuple[bool, str]:
    actor_role  = get_role(gang, actor_id)
    target_role = get_role(gang, target_id)
    if actor_role not in ("head", "vice", "recruiter"):
        return False, "You don't have permission to kick."
    if target_role == "head":
        return False, "❌ Cannot kick the Head."
    if actor_role == "vice" and target_role == "vice":
        return False, "❌ Vice Head cannot kick another Vice Head."
    if actor_role == "recruiter" and target_role in ("vice", "recruiter", "elder"):
        return False, "❌ Recruiters can only kick regular Members."
    return True, ""


def can_promote(gang: dict[str, Any], actor_id: str) -> bool:
    return get_role(gang, actor_id) in ("head", "vice")


def enforce_max_members(gang: dict[str, Any]) -> bool:
    members = gang.get("members", [])
    count   = len(members) if isinstance(members, list) else 0
    return count < MAX_MEMBERS


def set_role(gang: dict[str, Any], user_id: str, role: str) -> None:
    if role == "head":
        return
    roles = gang.setdefault("roles", {})
    if not isinstance(roles, dict):
        gang["roles"] = {}
        roles = gang["roles"]
    if role == "member":
        roles.pop(str(user_id), None)
    else:
        roles[str(user_id)] = role


def remove_from_gang(gang: dict[str, Any], user_id: str) -> None:
    uid = str(user_id)
    members = gang.get("members", [])
    if isinstance(members, list):
        gang["members"] = [str(m) for m in members if str(m) != uid]
    roles = gang.get("roles", {})
    if isinstance(roles, dict):
        roles.pop(uid, None)


def get_user_gang(data: dict[str, Any], user_id: str) -> tuple[str | None, dict[str, Any] | None]:
    players = data.get("players", {})
    player  = players.get(str(user_id)) if isinstance(players, dict) else None
    if not isinstance(player, dict):
        return None, None
    gang_id = player.get("gang_id")
    if not gang_id:
        return None, None
    gangs = data.get("gangs", {})
    gang  = gangs.get(str(gang_id)) if isinstance(gangs, dict) else None
    if not isinstance(gang, dict):
        return None, None
    return str(gang_id), gang


def find_gang_by_name(data: dict[str, Any], name: str) -> tuple[str | None, dict[str, Any] | None]:
    gangs = data.get("gangs", {})
    if not isinstance(gangs, dict):
        return None, None
    nl = str(name).strip().lower()
    for gid, gang in gangs.items():
        if isinstance(gang, dict) and str(gang.get("name", "")).lower() == nl:
            return str(gid), gang
    return None, None


def format_member_line(data: dict[str, Any], gang: dict[str, Any], user_id: str) -> str:
    uid     = str(user_id)
    icon    = get_role_icon(gang, uid, data)
    label   = get_role_label(gang, uid)
    players = data.get("players", {})
    player  = players.get(uid, {}) if isinstance(players, dict) else {}
    user    = player.get("user", {}) if isinstance(player, dict) else {}
    # Try name first, then username, then Discord mention as last resort
    name = None
    if isinstance(user, dict):
        name = user.get("name") or user.get("username") or user.get("display_name")
    if not name or str(name).strip() == uid:
        name = f"<@{uid}>"  # Discord mention so it shows properly
    else:
        name = f"@{str(name).strip()}"
    return f"{icon} {label:<12} {name}"
