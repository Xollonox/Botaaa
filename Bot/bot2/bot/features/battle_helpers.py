"""Battle helpers — shared functions used by battle views and cog."""

from __future__ import annotations

import re
import logging
from typing import Any

import discord
from discord.ext import commands

from bot.utils.battle_engine_pdf import normalize_attack_type
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed

logger = logging.getLogger(__name__)

TURN_TIMEOUT_SECONDS = 60
TURN_VIEW_TIMEOUT_SECONDS = 90
IDLE_SKIP_LIMIT_VS_CPU = 2
CPU_STALL_TIMEOUT_SECONDS = 180

CPU_NAMES = ["Gun Park", "Goo Kim", "James Lee", "Kitae Kim", "Daniel Park", "UI Daniel"]
CPU_PERSONALITIES = ["Aggressive", "Defensive", "Balanced", "Trickster", "Finisher"]
CPU_TROPHY_OFFSET = {"Aggressive": 50, "Defensive": 30, "Balanced": 0, "Trickster": 20, "Finisher": 40}

BATTLE_ERROR_TEXT = {
    "battle_not_found": "That battle panel is no longer active.",
    "battle_not_active": "This battle has already ended.",
    "not_in_battle": "You are not part of this battle.",
    "not_your_turn": "It is not your turn yet.",
    "attack_missing": "That move is not available for your current fighter.",
    "no_uses_left": "That move has no uses left for this battle.",
    "defense_already_used": "That defense type is already consumed for this fighter. Pick a different defense or attack.",
    "must_use_normal_or_defensive_first": "You cannot chain Special, Unique Skill, or Path moves back-to-back. Use a normal or defense first.",
    "unique_skill_already_used": "That unique skill was already used by this fighter in this battle.",
    "unique_path_already_used": "That path move was already used by this fighter in this battle.",
    "ultimate_limit_reached": "Your team has reached its ultimate quota for this match.",
    "ultimate_already_used_by_fighter": "That fighter already spent its one ultimate for this match.",
    "exhausted_must_use_normal": "Fighter is exhausted! Only normal attacks are available.",
    "invalid_switch": "That switch target is invalid.",
    "fighter_fainted": "You cannot switch to a fainted fighter.",
    "switch_apply_failed": "The switch could not be applied cleanly. Try again.",
    "missing_squad": "A valid active squad is required before battling.",
    "already_active": "That fighter is already active.",
    "no_active_fighter": "No active fighter is available on one side.",
    "swap_used": "You've already used your one swap this battle.",
}


async def battle_warn(interaction: Any, embed: Any, delete_after: float = 1.5) -> None:
    """Send an ephemeral-style warning that auto-deletes after a short delay."""
    try:
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, ephemeral=True, wait=True)
            if msg:
                import asyncio
                await asyncio.sleep(delete_after)
                try:
                    await msg.delete()
                except Exception:
                    logger.exception("Failed to auto-delete battle warning message")
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=delete_after)
    except Exception:
        logger.exception("Failed to send battle warning")


def battle_error_text(code: Any) -> str:
    key = str(code or "unknown")
    return BATTLE_ERROR_TEXT.get(key, key.replace("_", " ").capitalize())


async def defer_component_update(interaction: discord.Interaction) -> None:
    """Compatibility defer for component interactions across discord.py variants."""
    if interaction.response.is_done():
        return
    defer_update = getattr(interaction.response, "defer_update", None)
    if callable(defer_update):
        try:
            await defer_update()
        except Exception:
            logger.exception("defer_update failed")
        return
    try:
        await interaction.response.defer()
    except Exception:
        logger.exception("interaction.response.defer failed")


def cpu_name_pool(data: dict[str, Any]) -> list[str]:
    """Build CPU name pool from ai.roster names, with static fallback."""
    ai = data.get("ai", {}) if isinstance(data, dict) else {}
    roster = ai.get("roster", {}) if isinstance(ai, dict) else {}
    names: list[str] = []
    if isinstance(roster, dict):
        for value in roster.values():
            if not isinstance(value, dict):
                continue
            name = str(value.get("name", "")).strip()
            if name and name not in names:
                names.append(name)
    return names or list(CPU_NAMES)


def default_uses_by_type(move_type: str) -> int | None:
    t = normalize_attack_type(str(move_type or "normal"))
    if t in {"unique_skill", "unique_path", "block", "dodge", "revert", "parry", "defensive"}:
        return 1
    return None


def parse_int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def card_image_url(card: dict[str, Any] | None) -> str | None:
    if not isinstance(card, dict):
        return None
    url = str(card.get("image_url") or card.get("image") or card.get("img_url") or card.get("img") or card.get("card_image") or "").strip()
    return url if url.startswith("http") else None


def option_emoji(raw: Any) -> str | discord.PartialEmoji | None:
    value = str(raw or "").strip()
    if not value or value == "•":
        return None
    if value.startswith("<:") or value.startswith("<a:"):
        try:
            return discord.PartialEmoji.from_str(value)
        except Exception:
            return None
    return None


def clean_option_label(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return "Move"
    value = re.sub(r"^(?:<a?:\w+:\d+>\s*)+", "", value).strip()
    return value or "Move"


def get_assigned_attacks(card_item: dict[str, Any], card_def: dict[str, Any] | None = None) -> dict[str, list[str]]:
    assigned = card_item.get("assigned_attacks") if isinstance(card_item.get("assigned_attacks"), dict) else None
    if not isinstance(assigned, dict):
        assigned = card_item.get("attacks") if isinstance(card_item.get("attacks"), dict) else None
    out: dict[str, list[str]] = {"normal": [], "special": [], "unique_skill": [], "unique_path": []}
    if isinstance(assigned, dict):
        for k in out:
            vals = assigned.get(k, [])
            if isinstance(vals, list):
                out[k] = [str(v) for v in vals if str(v)]
            elif vals:
                out[k] = [str(vals)]
        return out

    base = card_def.get("attacks", []) if isinstance(card_def, dict) and isinstance(card_def.get("attacks", []), list) else []
    out["normal"] = [str(v) for v in base if str(v)]
    for k in ("unique_skill", "unique_path"):
        val = card_def.get(k) if isinstance(card_def, dict) else None
        if isinstance(val, list):
            out[k] = [str(v) for v in val if str(v)]
        elif val:
            out[k] = [str(val)]
    return out


def norm_lines(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    items: list[str] = []
    if isinstance(value, str):
        items = [x.strip() for x in value.splitlines()]
    elif isinstance(value, list):
        items = [str(x).strip() for x in value]
    for it in items:
        if not it:
            continue
        key = it.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def normalize_card_moves(card: dict[str, Any]) -> dict[str, list[str]]:
    c = card if isinstance(card, dict) else {}
    moves = c.get("moves", {}) if isinstance(c.get("moves", {}), dict) else {}
    out = {
        "normal": [],
        "special": [],
        "unique_skill": [],
        "unique_skill": [],
        "unique_path": [],
        "defensive": [],
    }

    out["normal"] = norm_lines(moves.get("normal", []))
    out["special"] = norm_lines(moves.get("special", []))
    out["unique_skill"] = norm_lines(moves.get("unique_skill", []))
    out["unique_skill"] = norm_lines(moves.get("unique_skill", []))
    out["unique_path"] = norm_lines(moves.get("unique_path", []))
    out["defensive"] = norm_lines(moves.get("defensive", []))

    if not out["normal"]:
        out["normal"] = norm_lines(c.get("normal_moves", [])) or norm_lines(c.get("attacks", [])) or norm_lines(c.get("moves_normal", [])) or norm_lines(c.get("moves_normal_text", ""))
    if not out["special"]:
        out["special"] = norm_lines(c.get("special_moves", [])) or norm_lines(c.get("special", []))
    if not out["unique_skill"]:
        out["unique_skill"] = norm_lines(c.get("ultimate_moves", [])) or norm_lines(c.get("unique_skill", []))
    if not out["unique_skill"]:
        out["unique_skill"] = norm_lines(c.get("unique_skill_moves", [])) or norm_lines(c.get("unique_skill", []))
    if not out["unique_path"]:
        out["unique_path"] = norm_lines(c.get("unique_path_moves", [])) or norm_lines(c.get("unique_path", []))
    if not out["defensive"]:
        out["defensive"] = norm_lines(c.get("defensive_moves", []))

    if not out["defensive"]:
        out["defensive"] = ["Block", "Dodge", "Revert", "Parry", "Tank"]

    if not any(out[k] for k in ("normal", "special", "unique_skill", "unique_skill", "unique_path")):
        out["normal"] = ["Basic Strike"]

    return out


def json_safe_battle_state(state: dict[str, Any]) -> None:
    for key in ("used_defenses_by_char_uid", "used_unique_skills_by_char_uid"):
        container = state.get(key)
        if not isinstance(container, dict):
            continue
        for uid, value in list(container.items()):
            if isinstance(value, set):
                container[uid] = [str(x) for x in value]
            elif isinstance(value, list):
                container[uid] = [str(x) for x in value]
