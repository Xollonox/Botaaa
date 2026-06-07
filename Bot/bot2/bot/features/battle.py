"""Battle commands: queue, friendly challenge, and attack-catalog integrated turn UI."""

from __future__ import annotations

import asyncio
import logging
import random
import traceback
from collections import defaultdict
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from bot.config import OWNER_GUILD_ID

from bot.utils.attacks_logic import ensure_attacks_structure
from bot.utils.battle_engine_pdf import normalize_attack_type
from bot.utils.battle_state import apply_move, create_battle_state, end_battle
from bot.utils.checks import ensure_registered, is_owner
from bot.utils.squad_logic import get_player, get_squad
from bot.utils.server_rules import check_battle_channel_allowed
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed, mini_bar, style_view
from bot.utils.interaction_visibility import smart_reply, error_reply

from bot.features.battle_helpers import (
    battle_warn,
    battle_error_text,
    defer_component_update,
    cpu_name_pool,
    default_uses_by_type,
    parse_int_or_none,
    card_image_url,
    option_emoji,
    clean_option_label,
    get_assigned_attacks,
    normalize_card_moves,
    json_safe_battle_state,
    CPU_NAMES,
    CPU_PERSONALITIES,
    CPU_TROPHY_OFFSET,
    TURN_TIMEOUT_SECONDS,
    TURN_VIEW_TIMEOUT_SECONDS,
    IDLE_SKIP_LIMIT_VS_CPU,
    CPU_STALL_TIMEOUT_SECONDS,
)

from bot.features.battle_views import (
    TurnView,
    FriendlyInviteView,
    RankedQueueView,
    ForfeitButton,
)

logger = logging.getLogger(__name__)
OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)
RANKED_QUEUE_TIMEOUT_SECONDS = 60


def _cpu_pick_move(personality: str, available_moves: list, fighter_hp_pct: float, enemy_hp_pct: float) -> str:
    """Pick a move for the CPU based on personality.

    Args:
        personality: personality name string
        available_moves: list of move type strings that still have uses
            (e.g. ["normal", "special", "ultimate", "block", "dodge"])
        fighter_hp_pct: current fighter's HP as 0.0-1.0
        enemy_hp_pct: enemy fighter's HP as 0.0-1.0
    Returns:
        move type string to use
    """
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


def build_battle_stats_embed(battle_state: dict, winner_name: str) -> discord.Embed:
    """Build a post-battle scoreboard embed from the finished battle state."""
    embed = discord.Embed(title="⚔️ Battle Summary", color=0x2B2D31)

    # ── Outcome label ────────────────────────────────────────────────
    reason = str(battle_state.get("reason", ""))
    outcome_map = {
        "all_fainted":        "KO",
        "no_active_fighter":  "KO",
        "forfeit":            "Forfeit",
        "timeout_abandoned":  "Timeout (No Contest)",
        "abandoned":          "No Contest",
        "no_contest":         "No Contest",
        "draw":               "Draw",
    }
    outcome_label = outcome_map.get(reason, reason.replace("_", " ").title() if reason else "Unknown")

    # ── Rounds / duration ────────────────────────────────────────────
    rounds = int(battle_state.get("round", 1))
    created_at = int(battle_state.get("created_at", 0))
    last_ts = int(battle_state.get("turn_started_at", 0))
    duration_str: str | None = None
    if created_at and last_ts and last_ts > created_at:
        secs = last_ts - created_at
        duration_str = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"

    # ── Parse log for per-player damage + move counts ────────────────
    # Log entries for attacks follow the format  "pid:move_type:damage"
    players: dict[str, Any] = battle_state.get("players", {}) if isinstance(battle_state.get("players"), dict) else {}
    pid_list = list(players.keys())

    damage_by_pid: dict[str, int] = {pid: 0 for pid in pid_list}
    move_counts: dict[str, dict[str, int]] = {
        pid: {"normal": 0, "special": 0, "ultimate": 0, "unique_skill": 0, "unique_path": 0, "defensive": 0}
        for pid in pid_list
    }
    logs = battle_state.get("log", []) if isinstance(battle_state.get("log"), list) else []
    for entry in logs:
        if not isinstance(entry, str):
            continue
        parts = entry.split(":", 2)
        if len(parts) == 3 and parts[0] and parts[1]:
            pid, move_raw, dmg_raw = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if pid not in damage_by_pid:
                continue
            try:
                dmg = int(dmg_raw)
                if dmg > 0:
                    damage_by_pid[pid] += dmg
            except (ValueError, TypeError):
                pass
            norm = normalize_attack_type(move_raw)
            mc = move_counts[pid]
            if norm in {"block", "dodge", "revert", "parry", "tank"}:
                mc["defensive"] += 1
            elif norm in mc:
                mc[norm] += 1
            else:
                mc["normal"] += 1

    # ── Per-side helpers ─────────────────────────────────────────────
    def side_display(pid: str) -> str:
        pstate = players.get(pid, {}) if isinstance(players.get(pid), dict) else {}
        if isinstance(pstate, dict) and bool(pstate.get("is_cpu", False)):
            cpu_meta = pstate.get("cpu_meta", {}) or {}
            return str(cpu_meta.get("display_name", "🤖 CPU")) if isinstance(cpu_meta, dict) else "🤖 CPU"
        return f"<@{pid}>"

    def side_hp_line(pid: str) -> str:
        pstate = players.get(pid, {}) if isinstance(players.get(pid), dict) else {}
        if not isinstance(pstate, dict):
            return "—"
        hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
        hp_max = pstate.get("hp_max", {}) if isinstance(pstate.get("hp_max"), dict) else {}
        team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []
        alive = sum(1 for uid in team if int(hp.get(uid, 0)) > 0)
        total = len(team)
        rem_hp = sum(int(hp.get(uid, 0)) for uid in team)
        max_hp = sum(int(hp_max.get(uid, 1)) for uid in team)
        return f"{alive}/{total} fighters standing · {rem_hp}/{max_hp} HP"

    # ── Header row ───────────────────────────────────────────────────
    embed.add_field(name="Outcome", value=outcome_label, inline=True)
    embed.add_field(name="Rounds", value=str(rounds), inline=True)
    embed.add_field(name="Duration", value=duration_str if duration_str else "—", inline=True)
    embed.add_field(name="🏆 Winner", value=winner_name or "—", inline=False)

    # ── Per-side breakdown ───────────────────────────────────────────
    for pid in pid_list:
        mc = move_counts.get(pid, {})
        move_parts: list[str] = []
        for label, key in (("Normal", "normal"), ("Special", "special"), ("Ultimate", "ultimate"),
                           ("Skill", "unique_skill"), ("Path", "unique_path"), ("Defense", "defensive")):
            if mc.get(key, 0):
                move_parts.append(f"{label} ×{mc[key]}")

        lines: list[str] = [side_hp_line(pid)]
        dmg = damage_by_pid.get(pid, 0)
        if dmg > 0:
            lines.append(f"Damage dealt: **{dmg}**")
        if move_parts:
            lines.append("Moves: " + "  ·  ".join(move_parts))

        # Add milestone packs if any were granted
        packs_key = f"{pid}_milestone_packs"
        if packs_key in battle_state and isinstance(battle_state[packs_key], list):
            packs = battle_state[packs_key]
            if packs:
                pack_names = [p.replace("_", " ").title() for p in packs]
                lines.append(f"🎁 Milestone Pack: {', '.join(pack_names)}")

        embed.add_field(name=side_display(pid), value="\n".join(lines), inline=True)

    # Also check winner_milestone_packs and loser_milestone_packs if used
    if "winner_milestone_packs" in battle_state and battle_state["winner_milestone_packs"]:
        packs = battle_state["winner_milestone_packs"]
        pack_names = [p.replace("_", " ").title() for p in packs]
        embed.add_field(name="🎁 Winner Milestone", value=", ".join(pack_names), inline=False)

    if "loser_milestone_packs" in battle_state and battle_state["loser_milestone_packs"]:
        packs = battle_state["loser_milestone_packs"]
        pack_names = [p.replace("_", " ").title() for p in packs]
        embed.add_field(name="🎁 Loser Milestone", value=", ".join(pack_names), inline=False)

    embed.set_footer(text="Battle Stats")
    return embed


class BattleCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.turn_tasks: dict[str, asyncio.Task[Any]] = {}
        self.battle_stall_tasks: dict[str, asyncio.Task[Any]] = {}
        self.timer_tasks: dict[str, asyncio.Task[Any]] = {}
        self.queue_cpu_tasks: dict[str, asyncio.Task[Any]] = {}
        self.friendly_cpu_tasks: dict[str, asyncio.Task[Any]] = {}
        # cpu_win_timestamps moved to player data (persistent) in battle_state.end_battle

    def _track_background_task(
        self,
        bucket: dict[str, asyncio.Task[Any]],
        key: str,
        task: asyncio.Task[Any],
        label: str,
    ) -> None:
        task_key = str(key)
        bucket[task_key] = task

        def on_done(done: asyncio.Task[Any]) -> None:
            if bucket.get(task_key) is done:
                bucket.pop(task_key, None)
            try:
                exc = done.exception()
            except asyncio.CancelledError:
                logger.debug("[BATTLE_TASK_CANCELLED] label=%s key=%s", label, task_key)
                return
            if exc is not None:
                logger.error(
                    "[BATTLE_TASK_ERROR] label=%s key=%s",
                    label,
                    task_key,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(on_done)

    def _cancel_battle_runtime_tasks(self, battle_id: str) -> None:
        current_task = asyncio.current_task()
        for bucket in (self.turn_tasks, self.battle_stall_tasks, self.timer_tasks):
            task = bucket.pop(str(battle_id), None)
            if task and task is not current_task and not task.done():
                task.cancel()

    async def _tick_timer(self, battle_id: str, total: int) -> None:
        """E. Live turn timer — edit battle message every 10 seconds with updated countdown."""
        for remaining in range(total - 10, 0, -10):
            await asyncio.sleep(10)
            data = self.bot.storage.load()
            battle = self._battle_root(data).get("active", {}).get(battle_id)
            if not isinstance(battle, dict) or bool(battle.get("ended", False)):
                return
            channel_id = int(str(battle.get("message_channel_id", 0)) or 0)
            message_id = int(str(battle.get("message_id", 0)) or 0)
            if not channel_id or not message_id:
                return
            channel = self.bot.get_channel(channel_id)
            if channel is None or not hasattr(channel, "fetch_message"):
                return
            try:
                msg = await channel.fetch_message(message_id)
            except Exception:
                return
            embed_a, embed_b, embed_c, _view = self._build_embed_view(data, battle_id)
            try:
                await msg.edit(embeds=[emb for emb in (embed_a, embed_b, embed_c) if emb is not None])
            except Exception:
                logger.debug("[TIMER_TICK] edit failed battle_id=%s remaining=%s", battle_id, remaining)

    async def _apply_battle_message_update(self, interaction: discord.Interaction, *, embeds: list[discord.Embed], view: discord.ui.View | None) -> None:
        if view is not None:
            style_view(view, self.bot.storage.load())
        if interaction.response.is_done() and getattr(interaction, "message", None) is not None:
            if view is not None and hasattr(view, "message"):
                view.message = interaction.message
            await interaction.message.edit(embeds=embeds, view=view, attachments=[])
            return
        if interaction.response.is_done():
            await interaction.edit_original_response(embeds=embeds, view=view, attachments=[])
            return
        await interaction.response.edit_message(embeds=embeds, view=view)

    def _battle_root(self, data: dict[str, Any]) -> dict[str, Any]:
        root = data.setdefault("battle", {})
        root.setdefault("queue", [])
        root.setdefault("pending_friendly", {})
        root.setdefault("active", {})
        root.setdefault("active_by_user", {})
        return root

    def _lookup_battle(self, data: dict[str, Any], battle_id: str) -> dict[str, Any] | None:
        """Look up a battle by ID, checking active first then recently_ended."""
        root = self._battle_root(data)
        state = root.get("active", {}).get(battle_id)
        if isinstance(state, dict):
            return state
        for entry in root.get("recently_ended", []):
            if isinstance(entry, dict) and str(entry.get("battle_id", "")) == battle_id:
                return entry
        return None

    async def _load_battle_data(self) -> dict[str, Any]:
        data = self.bot.storage.load()
        return await self.bot.battle_service.hydrate_json_state(data)

    def _cleanup_expired(self, data: dict[str, Any]) -> None:
        now = now_ts()
        root = self._battle_root(data)
        root["queue"] = [q for q in root.get("queue", []) if isinstance(q, dict) and int(q.get("expires_at", 0)) > now]
        pending = root.get("pending_friendly", {})
        if isinstance(pending, dict):
            for key, value in list(pending.items()):
                if not isinstance(value, dict) or int(value.get("expires_at", 0)) <= now:
                    pending.pop(key, None)

    def _active_battle_id(self, data: dict[str, Any], user_id: str) -> str:
        return str(self._battle_root(data).get("active_by_user", {}).get(user_id, ""))

    def _snapshot_team(self, data: dict[str, Any], user_id: str) -> list[str]:
        """
        Build the battle team from the full squad, not just the active lane.

        Order is preserved as:
        - active slots first
        - backup slots next

        This allows 1v1 through 4v4 naturally while keeping the hard squad cap
        at four fighters total.
        """
        player = get_player(data, user_id)
        if not isinstance(player, dict):
            return []
        squad = get_squad(player)

        ordered: list[str] = []
        seen: set[str] = set()
        for slot in ("active", "backup"):
            values = squad.get(slot, [])
            if not isinstance(values, list):
                continue
            for raw_uid in values:
                uid = str(raw_uid).strip()
                if not uid or uid in seen:
                    continue
                ordered.append(uid)
                seen.add(uid)
                if len(ordered) >= 4:
                    return ordered
        return ordered

    def _player_trophies(self, data: dict[str, Any], user_id: str) -> int:
        p = get_player(data, user_id)
        if not isinstance(p, dict):
            return 0
        return int(p.get("user", {}).get("trophies", 0))

    def _participant_id(self, participant: dict[str, Any] | None, fallback_user_id: str) -> str:
        if isinstance(participant, dict) and bool(participant.get("cpu", False)):
            return str(participant.get("cpu_key", fallback_user_id))
        return str(fallback_user_id)

    def _make_cpu_participant(self, data: dict[str, Any], player_trophies: int) -> dict[str, Any]:
        personality = random.choice(CPU_PERSONALITIES)
        name = random.choice(cpu_name_pool(data))
        tc = max(0, int(player_trophies) + int(CPU_TROPHY_OFFSET.get(personality, 0)) + random.randint(-25, 25))
        return {
            "cpu": True,
            "cpu_key": f"cpu:{name}:{personality}",
            "display_name": f"🤖 CPU: {name}",
            "personality": personality,
            "trophies": tc,
            "avatar_url": None,
        }

    def _elo_cpu_delta(self, player_trophies: int, cpu_trophies: int, won: bool) -> int:
        tp = int(player_trophies)
        tc = int(cpu_trophies)
        ew = 1 / (1 + 10 ** ((tc - tp) / 400))
        k = 22
        if tp < 500:
            k = 28
        elif tp > 2000:
            k = 16
        delta = round(k * ((1 - ew) if won else (0 - ew)))
        if won:
            delta = max(4, min(22, delta))
        else:
            delta = max(-22, min(-4, delta))
        return int(delta)

    def _init_attack_uses_for_battle(self, data: dict[str, Any], battle_id: str) -> None:
        ensure_attacks_structure(data)
        catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return

        players = battle.get("players", {})
        if not isinstance(players, dict):
            return

        for pid, pstate in players.items():
            if not isinstance(pstate, dict):
                continue
            pstate.setdefault("attack_uses", {})
            attack_uses = pstate["attack_uses"]
            team = pstate.get("team_uids", [])
            if bool(pstate.get("is_cpu", False)):
                assigned_map = pstate.get("assigned_attacks_by_uid", {}) if isinstance(pstate.get("assigned_attacks_by_uid"), dict) else {}
                inv_map: dict[str, Any] = {}
            else:
                player = get_player(data, str(pid))
                inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
                inv_map = {str(i.get("uid", "")): i for i in inv if isinstance(i, dict)} if isinstance(inv, list) else {}
                assigned_map = {}

            for uid in team if isinstance(team, list) else []:
                if bool(pstate.get("is_cpu", False)):
                    # For CPU: read moves from the card definition via fighter_names
                    names = pstate.get("fighter_names", {}) if isinstance(pstate.get("fighter_names"), dict) else {}
                    card_name = str(names.get(uid, ""))
                    card_def = data.get("cards", {}).get(card_name) if isinstance(data.get("cards", {}), dict) else None
                    # Use normalize_card_moves (from battle_helpers)
                    if isinstance(card_def, dict):
                        cm = normalize_card_moves(card_def)
                        attacks = []
                        for k in ("normal", "special", "ultimate", "unique_skill", "unique_path"):
                            attacks.extend(cm.get(k, []))
                    else:
                        attacks = []
                else:
                    inst = inv_map.get(uid)
                    card_name = str(inst.get("card_name", "")) if isinstance(inst, dict) else ""
                    card_def = data.get("cards", {}).get(card_name) if isinstance(data.get("cards", {}), dict) else None
                    attacks = card_def.get("attacks", []) if isinstance(card_def, dict) else []
                if not isinstance(attacks, list):
                    attacks = []
                attack_uses[uid] = {}
                for key in attacks:
                    k = str(key)
                    entry = catalog.get(k, {}) if isinstance(catalog, dict) else {}
                    if isinstance(entry, dict) and "uses_per_battle" in entry:
                        raw_uses = parse_int_or_none(entry.get("uses_per_battle"))
                        uses = raw_uses if raw_uses is not None else default_uses_by_type(str(entry.get("type", "normal")))
                    else:
                        uses = default_uses_by_type(str(entry.get("type", "normal"))) if isinstance(entry, dict) else default_uses_by_type("normal")
                    attack_uses[uid][k] = -1 if uses is None else int(uses)

                # keep legacy per-type limits from blocking per-attack mode
                legacy = pstate.get("uses", {}).get(uid)
                if isinstance(legacy, dict):
                    legacy["special_left"] = 999
                    legacy["ultimate_left"] = 999
                    legacy["unique_skill_left"] = 999
                    legacy["unique_path_left"] = 999


    def _resolve_active_uid(self, pstate: dict[str, Any]) -> str | None:
        if not isinstance(pstate, dict):
            return None
        team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []
        if not team:
            return None
        hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
        idx = int(pstate.get("active_index", pstate.get("current_index", 0)))
        if 0 <= idx < len(team):
            uid = str(team[idx])
            if int(hp.get(uid, 0)) > 0:
                pstate["current_index"] = idx
                pstate["active_index"] = idx
                return uid
        for i, uid in enumerate(team):
            if int(hp.get(str(uid), 0)) > 0:
                pstate["current_index"] = i
                pstate["active_index"] = i
                logger.warning("[ACTIVE_RESOLVE] repaired active index -> %s", i)
                return str(uid)
        return None

    def _resolve_switch_target_index(self, pstate: dict[str, Any], selected_value: str | None) -> int | None:
        if not isinstance(pstate, dict):
            return None
        team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []
        if not team:
            return None
        raw = str(selected_value or "").strip()
        if raw.isdigit():
            idx = int(raw)
            return idx if 0 <= idx < len(team) else None
        for i, uid in enumerate(team):
            if str(uid) == raw:
                return i
        return None

    def _apply_switch(self, battle: dict[str, Any], actor_id: str, target_index: int) -> dict[str, Any]:
        players = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
        me = players.get(actor_id) if isinstance(players.get(actor_id), dict) else None
        if not isinstance(me, dict):
            return {"ok": False, "error": "invalid_participants"}
        team = me.get("team_uids", []) if isinstance(me.get("team_uids"), list) else []
        hp = me.get("hp", {}) if isinstance(me.get("hp"), dict) else {}
        if not team or target_index < 0 or target_index >= len(team):
            return {"ok": False, "error": "invalid_switch"}

        current_uid = self._resolve_active_uid(me)
        if current_uid is None:
            return {"ok": False, "error": "no_active_fighter"}
        prev_idx = int(me.get("active_index", me.get("current_index", 0)))
        target_uid = str(team[target_index])
        logger.info("[SWITCH] side=%s previous_active=%s selected=%s", actor_id, prev_idx, target_index)

        if target_uid == current_uid:
            return {"ok": False, "error": "already_active"}
        if int(hp.get(target_uid, 0)) <= 0:
            return {"ok": False, "error": "fighter_fainted"}

        # Cap voluntary swaps to 1 per battle (forced post-faint swaps go through
        # _sync_active_fighter in battle_state.py and don't increment this counter).
        if not bool(me.get("is_cpu", False)):
            swaps_used = int(me.get("swaps_used", 0))
            if swaps_used >= 1:
                return {"ok": False, "error": "swap_used"}
            me["swaps_used"] = swaps_used + 1

        me["current_index"] = target_index
        me["active_index"] = target_index
        resolved_uid = self._resolve_active_uid(me)
        if resolved_uid != target_uid:
            return {"ok": False, "error": "switch_apply_failed"}

        fighter_names = me.get("fighter_names", {}) if isinstance(me.get("fighter_names"), dict) else {}
        card_name = str(fighter_names.get(target_uid, target_uid[:8]))
        logger.info("[SWITCH] resolved_target_index=%s", target_index)
        logger.info("[SWITCH] new_active_index=%s active_card=%s", target_index, card_name)

        actor_label = "🤖 CPU" if bool(me.get("is_cpu", False)) else f"<@{actor_id}>"
        prior = battle.get("log", []) if isinstance(battle.get("log"), list) else []
        prior.append(f"🔁 {actor_label} → {card_name}")
        battle["log"] = [str(x) for x in prior][-5:]

        enemy_id = next((str(pid) for pid in players.keys() if str(pid) != actor_id), "")
        battle["turn_user_id"] = enemy_id
        battle["turn_started_at"] = now_ts()
        battle["round"] = int(battle.get("round", 1)) + 1
        logger.info("[TURN] next_side=%s", enemy_id)
        return {"ok": True}
    def _current_uid(self, pstate: dict[str, Any]) -> str:
        team = pstate.get("team_uids", [])
        if not isinstance(team, list) or not team:
            return ""
        hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
        idx = int(pstate.get("active_index", pstate.get("current_index", 0)))
        if 0 <= idx < len(team):
            uid = str(team[idx])
            if int(hp.get(uid, 0)) > 0:
                pstate["current_index"] = idx
                pstate["active_index"] = idx
                return uid
        for i, uid in enumerate(team):
            if int(hp.get(str(uid), 0)) > 0:
                pstate["current_index"] = i
                pstate["active_index"] = i
                logger.warning("[BATTLE_STATE] auto-switched active fighter -> %s", i)
                return str(uid)
        pstate["current_index"] = 0
        pstate["active_index"] = 0
        return ""

    def _fighter_attack_rows(self, data: dict[str, Any], battle_id: str, actor_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ensure_attacks_structure(data)
        catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return [], []
        pstate = (battle.get("players", {}) or {}).get(actor_id)
        if not isinstance(pstate, dict):
            return [], []
        uid = self._current_uid(pstate)
        if not uid:
            return [], []

        card_def: dict[str, Any] = {}
        if bool(pstate.get("is_cpu", False)):
            names = pstate.get("fighter_names", {}) if isinstance(pstate.get("fighter_names"), dict) else {}
            card_name = str(names.get(uid, ""))
            cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
            maybe = cards.get(card_name, {}) if card_name else {}
            card_def = maybe if isinstance(maybe, dict) else {}
        else:
            player = get_player(data, actor_id)
            inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
            inst = None
            if isinstance(inv, list):
                for item in inv:
                    if isinstance(item, dict) and str(item.get("uid", "")) == uid:
                        inst = item
                        break
            card_name = str(inst.get("card_name", "")) if isinstance(inst, dict) else ""
            cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
            maybe = cards.get(card_name, {}) if card_name else {}
            card_def = maybe if isinstance(maybe, dict) else {}

        moves = normalize_card_moves(card_def)
        uses_map = pstate.get("attack_uses", {}).get(uid, {}) if isinstance(pstate.get("attack_uses", {}), dict) else {}
        used_defs_map = battle.get("used_defenses_by_char_uid", {}) if isinstance(battle.get("used_defenses_by_char_uid", {}), dict) else {}
        raw_used_defs = used_defs_map.get(uid, set())
        if isinstance(raw_used_defs, set):
            used_defs = {normalize_attack_type(str(x)) for x in raw_used_defs}
        elif isinstance(raw_used_defs, list):
            used_defs = {normalize_attack_type(str(x)) for x in raw_used_defs}
        else:
            used_defs = set()

        offensive: list[dict[str, Any]] = []
        defensive: list[dict[str, Any]] = []

        def add_row(key: str, attack_type: str) -> None:
            entry = catalog.get(key) if isinstance(catalog, dict) else None
            name = key
            power = None
            left = -1
            if isinstance(entry, dict):
                name = str(entry.get("name", key))
                power = parse_int_or_none(entry.get("power"))
                if key in uses_map:
                    left = int(uses_map.get(key, -1))
                elif "uses_per_battle" in entry:
                    parsed = parse_int_or_none(entry.get("uses_per_battle"))
                    left = -1 if parsed is None else int(parsed)
                else:
                    default_uses = default_uses_by_type(str(entry.get("type", attack_type)))
                    left = -1 if default_uses is None else int(default_uses)
            else:
                left = int(uses_map.get(key, -1))
            row = {"key": key, "name": name, "type": attack_type, "power": power, "left": left}
            norm_type = normalize_attack_type(attack_type)
            if norm_type in {"block", "dodge", "parry", "revert", "tank"}:
                if left != 0 and norm_type not in used_defs:
                    defensive.append(row)
            else:
                if left != 0:
                    offensive.append(row)

        for mv in moves.get("normal", []):
            add_row(str(mv), "normal")
        for mv in moves.get("special", []):
            add_row(str(mv), "special")
        for mv in moves.get("ultimate", []):
            add_row(str(mv), "ultimate")
        for mv in moves.get("unique_skill", []):
            add_row(str(mv), "unique_skill")
        for mv in moves.get("unique_path", []):
            add_row(str(mv), "unique_path")

        for mv in moves.get("defensive", []):
            norm = normalize_attack_type(str(mv))
            typ = norm if norm in {"block", "dodge", "revert", "parry", "tank"} else str(mv).lower()
            if typ in {"block", "dodge", "revert", "parry", "tank"}:
                add_row(str(mv), typ)

        if not defensive:
            for fallback in ("Block", "Dodge", "Revert", "Parry", "Tank"):
                add_row(fallback, fallback.lower())

        return offensive, defensive

    def _switch_options(self, data: dict[str, Any], battle_id: str, actor_id: str) -> list[discord.SelectOption]:
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return []
        pstate = (battle.get("players", {}) or {}).get(actor_id)
        if not isinstance(pstate, dict):
            return []

        # Human players get 1 voluntary swap per battle. CPU is unrestricted.
        if not bool(pstate.get("is_cpu", False)) and int(pstate.get("swaps_used", 0)) >= 1:
            return []

        uid = self._current_uid(pstate)
        hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
        hp_max = pstate.get("hp_max", {}) if isinstance(pstate.get("hp_max"), dict) else {}
        team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []

        player = get_player(data, actor_id)
        inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
        inv_map = {str(i.get("uid", "")): i for i in inv if isinstance(i, dict)} if isinstance(inv, list) else {}

        cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
        out: list[discord.SelectOption] = []
        for idx, u in enumerate(team, start=1):
            if u == uid:
                continue
            cur_hp = int(hp.get(u, 0))
            if cur_hp <= 0:
                continue
            item = inv_map.get(u, {})
            name = str(item.get("card_name", u[:8]))
            cdef = cards.get(name, {}) if isinstance(cards.get(name, {}), dict) else {}
            emoji = option_emoji(cdef.get("emoji", "🃏"))
            desc = f"S{idx} HP: {cur_hp}/{int(hp_max.get(u,0))}"
            out.append(discord.SelectOption(label=name[:100], description=desc[:100], value=u, emoji=emoji))
        return out

    def _moves_summary(self, offensive: list[dict[str, Any]]) -> str:
        counts = {"normal": 0, "special": 0, "ultimate": 0, "unique_skill": 0, "unique_path": 0}
        for row in offensive:
            t = str(row.get("type", "normal"))
            if t in counts:
                counts[t] += 1
        return f"N:{counts['normal']} S:{counts['special']} U:{counts['ultimate']} US:{counts['unique_skill']} UP:{counts['unique_path']}"

    def _uses_summary(self, offensive: list[dict[str, Any]]) -> str:
        lines = []
        for row in offensive[:10]:
            left = int(row.get("left", -1))
            uses = "∞" if left == -1 else str(left)
            lines.append(f"{row.get('name')}:{uses}")
        return "\n".join(lines) if lines else "-"

    def _build_embed_view(self, data: dict[str, Any], battle_id: str, display_hp_override: dict[str, int] | None = None) -> tuple[discord.Embed | None, discord.Embed | None, discord.Embed | None, TurnView | None]:
        try:
            battle = self._lookup_battle(data, battle_id)
            if not isinstance(battle, dict):
                return make_embed(data, "Battle Missing", "State not found."), None, None, None

            players = battle.get("players", {}) if isinstance(battle.get("players", {}), dict) else {}
            pids = list(players.keys())
            if len(pids) != 2:
                return make_embed(data, "Battle Invalid", "Invalid participants."), None, None, None

            a_id, b_id = str(pids[0]), str(pids[1])
            a = players.get(a_id, {}) if isinstance(players.get(a_id), dict) else {}
            b = players.get(b_id, {}) if isinstance(players.get(b_id), dict) else {}
            cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}

            def display_name(pid: str, pstate: dict[str, Any]) -> str:
                if bool(pstate.get("is_cpu", False)):
                    return str((pstate.get("cpu_meta", {}) or {}).get("display_name", "CPU"))
                return f"<@{pid}>"

            def fighter_bundle(uid: str, pstate: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                names = pstate.get("fighter_names", {}) if isinstance(pstate.get("fighter_names"), dict) else {}
                card_name = str(names.get(uid, uid[:8]))
                cdef = cards.get(card_name, {}) if isinstance(cards.get(card_name, {}), dict) else {}
                return card_name, cdef

            def hp_bar(pct: int, slots: int = 12) -> str:
                pct = max(0, min(100, pct))
                filled = round(pct / 100 * slots)
                return "█" * filled + "░" * (slots - filled)

            def side_panel(pid: str, pstate: dict[str, Any], label: str) -> str:
                uid = self._current_uid(pstate)
                hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
                hp_max = pstate.get("hp_max", {}) if isinstance(pstate.get("hp_max"), dict) else {}
                stats_map = pstate.get("stats", {}) if isinstance(pstate.get("stats"), dict) else {}
                card_name, cdef = fighter_bundle(uid, pstate)
                rarity = str(cdef.get("rarity", "")).strip()
                cur_hp = max(0, int(display_hp_override.get(uid, hp.get(uid, 0)) if display_hp_override else hp.get(uid, 0)))
                max_hp = max(1, int(hp_max.get(uid, 1)))
                cur_hp = min(cur_hp, max_hp)
                pct = int(round((cur_hp / max_hp) * 100))
                stats = stats_map.get(uid, {}) if isinstance(stats_map.get(uid, {}), dict) else {}

                def s(k: str) -> int:
                    return int(stats.get(k, 0))

                lines = [
                    f"**{label} — {display_name(pid, pstate)}**",
                    f"{card_name}  [{rarity}]",
                    f"HP: {hp_bar(pct)}  {cur_hp}/{max_hp} ({pct}%)",
                    f"STR {s('strength')} | SPD {s('speed')} | END {s('endurance')} | TEC {s('technique')} | IQ {s('iq')} | BIQ {s('biq')}",
                ]
                return "\n".join(lines)

            def squad_block(label: str, pstate: dict[str, Any]) -> str:
                team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []
                hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
                hp_max = pstate.get("hp_max", {}) if isinstance(pstate.get("hp_max"), dict) else {}
                cur_uid = self._current_uid(pstate)
                lines = [f"**{label}**"]
                for i, uid in enumerate(team, 1):
                    card_name, _ = fighter_bundle(str(uid), pstate)
                    cur = int(hp.get(uid, 0))
                    mx = int(hp_max.get(uid, 1))
                    is_active = str(uid) == cur_uid
                    is_fainted = cur <= 0
                    name_str = f"~~{card_name}~~" if is_fainted else card_name
                    status = "fainted" if is_fainted else ("active" if is_active else f"{cur}/{mx}")
                    marker = "▸" if is_active else "◦"
                    lines.append(f"{marker} {i}. {name_str} — {status}")
                return "\n".join(lines) if len(lines) > 1 else f"**{label}**\n-"

            # ── Log display ────────────────────────────────────────
            logs = battle.get("log", []) if isinstance(battle.get("log"), list) else []
            REJECTION_MAP = {
                "block_rejected":  "🛡  Block — Failed (outmatched)",
                "dodge_rejected":  "⚡  Dodge — Failed (too slow)",
                "revert_rejected": "🔄  Revert — Failed (overwhelmed)",
                "parry_rejected":  "🪃  Parry — Failed (force broke through)",
            }

            def fighter_label(pid: str) -> str:
                if not pid:
                    return "@Player"
                pstate = players.get(pid, {}) if isinstance(players.get(pid), dict) else {}
                if bool((pstate or {}).get("is_cpu", False)):
                    cpu_meta = (pstate.get("cpu_meta", {}) or {}) if isinstance(pstate, dict) else {}
                    raw_name = str(cpu_meta.get("display_name", "CPU")).strip()
                    return raw_name.replace("🤖 CPU:", "CPU").replace("🤖 CPU", "CPU").strip()
                player = get_player(data, pid)
                if isinstance(player, dict):
                    user = player.get("user", {}) if isinstance(player.get("user"), dict) else {}
                    name = str(user.get("display_name") or user.get("name") or user.get("username") or "").strip()
                    if name:
                        return f"@{name}"
                user = self.bot.get_user(int(pid)) if str(pid).isdigit() else None
                if user is not None:
                    name = str(getattr(user, "display_name", "") or getattr(user, "global_name", "") or getattr(user, "name", "")).strip()
                    if name:
                        return f"@{name}"
                return "@Player"

            def move_label(move_type: str) -> str:
                norm = normalize_attack_type(str(move_type or "normal"))
                if norm == "normal":
                    return "Normal Attack"
                if norm == "special":
                    return "Special Attack"
                if norm == "ultimate":
                    return "Ultimate Attack"
                if norm == "unique_skill":
                    return "Unique Skill"
                if norm == "unique_path":
                    return "Unique Path"
                if norm in {"block", "dodge", "revert", "parry", "tank"}:
                    return norm.title()
                return str(move_type or "Move").replace("_", " ").title()

            def move_emoji(move_type: str) -> str:
                norm = normalize_attack_type(str(move_type or "normal"))
                if norm == "normal":
                    return e("attack_normal", data)
                if norm == "special":
                    return e("attack_special", data)
                if norm == "ultimate":
                    return e("attack_ultimate", data)
                if norm == "unique_skill":
                    return e("attack_unique_skill", data)
                if norm == "unique_path":
                    return e("attack_unique_path", data)
                if norm == "block":
                    return e("def_block", data)
                if norm == "dodge":
                    return e("def_dodge", data)
                if norm == "revert":
                    return e("def_revert", data)
                if norm == "parry":
                    return e("def_parry", data)
                if norm == "tank":
                    return e("def_tank", data)
                if norm == "switch":
                    return e("switch", data)
                return e("common", data)

            def move_name_from_entry(move_type: str) -> str:
                norm = normalize_attack_type(str(move_type or "normal"))
                if isinstance(catalog := data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}, dict):
                    entry = catalog.get(str(move_type or ""), {})
                    if isinstance(entry, dict):
                        entry_name = str(entry.get("name", "")).strip()
                        entry_type = normalize_attack_type(str(entry.get("type", norm)))
                        if entry_name:
                            if entry_type in {"normal", "special", "ultimate", "unique_skill", "unique_path"}:
                                return entry_name
                            if entry_type in {"block", "dodge", "revert", "parry", "tank"}:
                                return entry_name
                if norm in {"normal", "special", "ultimate", "unique_skill", "unique_path"}:
                    return move_label(norm)
                if norm in {"block", "dodge", "revert", "parry", "tank"}:
                    return move_label(norm)
                return move_label(move_type)

            def format_log_entry(entry: str) -> str | None:
                text = str(entry or "").strip()
                if not text:
                    return None
                if text in REJECTION_MAP:
                    return REJECTION_MAP[text]
                if text.startswith("CPU chose:") or text.startswith("Personality:"):
                    return None
                if text.startswith("⏭ "):
                    raw = text[2:].strip()
                    pid = raw.split(" ", 1)[0].strip()
                    return f"{e('clock', data)} {fighter_label(pid)} skipped their turn"
                if text.startswith("🔁 "):
                    rest = text[2:].strip()
                    if " → " in rest:
                        left, right = rest.split(" → ", 1)
                        pid = left.strip()
                        target = right.strip()
                        return f"{move_emoji('switch')} {fighter_label(pid)} switched to {target}"
                if " prepares " in text:
                    pid, _, move_txt = text.partition(" prepares ")
                    prepared = move_label(move_txt.strip())
                    return f"{move_emoji(move_txt.strip())} {fighter_label(pid.strip())} prepared {prepared}"
                if ":" in text:
                    parts = text.split(":", 2)
                    if len(parts) == 3 and parts[0] and parts[1]:
                        pid, move_type, damage_raw = parts
                        try:
                            damage = int(damage_raw)
                        except Exception:
                            damage = None
                        if damage is None:
                            result = "resolved"
                        elif damage <= 0:
                            result = "dealt no damage"
                        else:
                            result = f"dealt {damage} damage"
                        attack_name = move_name_from_entry(move_type.strip())
                        return f"{move_emoji(move_type.strip())} {fighter_label(pid.strip())} used {attack_name} and {result}"
                return text

            display_logs = []
            for x in logs:
                if not isinstance(x, str) or not x.strip():
                    continue
                formatted = format_log_entry(x)
                if formatted:
                    display_logs.append(formatted)
            # Only show newest 3 log entries
            log_text = "\n".join(display_logs[-3:]) if display_logs else "—"

            # ── Turn info ──────────────────────────────────────────
            turn_user = str(battle.get("turn_user_id", ""))
            turn_state = players.get(turn_user, {}) if isinstance(players.get(turn_user), dict) else {}
            round_no = int(battle.get("round", 1))

            timer = max(0, TURN_TIMEOUT_SECONDS - max(0, now_ts() - int(battle.get("turn_started_at", 0))))
            turn_label = "CPU" if bool((turn_state or {}).get("is_cpu", False)) else f"<@{turn_user}>"
            mode_label = str(battle.get("type", "ranked")).upper()

            # ── Thumbnails for each side's active fighter ────────
            a_uid = self._current_uid(a) if isinstance(a, dict) else ""
            a_img = card_image_url(fighter_bundle(a_uid, a)[1]) if a_uid else None
            b_uid = self._current_uid(b) if isinstance(b, dict) else ""
            b_img = card_image_url(fighter_bundle(b_uid, b)[1]) if b_uid else None

            # ── Build three embeds ─────────────────────────────────
            desc_a = (
                f"{side_panel(a_id, a, 'Side A')}\n\n"
                f"{squad_block('Squad', a)}"
            )
            desc_b = (
                f"{side_panel(b_id, b, 'Side B')}\n\n"
                f"{squad_block('Squad', b)}"
            )

            header = f"{mode_label} DUEL — Round {round_no} — Turn: {turn_label} — {timer}s"
            embed_a = make_embed(None, header, desc_a, color=0x2b2d31, image_url=a_img)
            embed_b = make_embed(None, "", desc_b, color=0x2b2d31, image_url=b_img)
            log_display = log_text[:1024] if log_text else "—"
            embed_c = make_embed(None, f"{e('list', data)} Battle Log", log_display, color=0x2b2d31, footer=f"Round {round_no}")

        except Exception:
            logger.exception("[BATTLE_EMBED_ERROR] battle_id=%s", battle_id)
            # Return a basic view with forfeit button so user can always escape
            fallback_view = discord.ui.View(timeout=300)
            fallback_btn = discord.ui.Button(label="🏳️ Forfeit", style=discord.ButtonStyle.danger, row=0)
            async def fb_cb(i: discord.Interaction):
                await self.forfeit_internal(i, str(i.user.id))
            fallback_btn.callback = fb_cb
            fallback_view.add_item(fallback_btn)
            return make_embed(data, "Battle Error", "battle state error"), None, None, fallback_view

        if bool(battle.get("ended", False)):
            end_reason = str(battle.get("reason", ""))
            if end_reason in {"timeout_abandoned", "abandoned", "no_contest"}:
                result_lines = [
                    "No Contest",
                    "Battle ended due to inactivity.",
                    "No trophies or rewards were granted.",
                ]
                embed_a.description = "─" * 32 + "\n" + "\n".join(result_lines) + "\n" + "─" * 32 + "\n\n" + (embed_a.description or "")
                embed_c_log = make_embed(None, f"{e('list', data)} Battle Log — Ended", log_text[:1024] if log_text else "—", color=0x2b2d31)
                return embed_a, embed_b, embed_c_log, None

            if end_reason == "draw":
                result_lines = [
                    "🤝 Draw",
                    "Both sides were knocked out at the same time.",
                ]
                embed_a.description = "─" * 32 + "\n" + "\n".join(result_lines) + "\n" + "─" * 32 + "\n\n" + (embed_a.description or "")
                embed_c_log = make_embed(None, "Battle Log — Ended", log_text[:1024] if log_text else "—", color=0x2b2d31)
                return embed_a, embed_b, embed_c_log, None

            winner = str(battle.get("winner_id", ""))
            loser = b_id if winner == a_id else a_id
            winner_state = players.get(winner, {}) if isinstance(players.get(winner), dict) else {}
            loser_state = players.get(loser, {}) if isinstance(players.get(loser), dict) else {}
            winner_name = "🤖 CPU" if bool(winner_state.get("is_cpu", False)) else (f"<@{winner}>" if winner else "Unknown")
            loser_name = "🤖 CPU" if bool(loser_state.get("is_cpu", False)) else (f"<@{loser}>" if loser else "Unknown")
            trophy_changes = battle.get("pvp_trophy_changes", {})
            cpu_trophy_change = battle.get("cpu_trophy_change")
            coin_reward = battle.get("coin_reward")

            result_lines = [
                f"🏆 Winner: {winner_name}",
                f"💀 Loser:  {loser_name}",
            ]
            if trophy_changes and isinstance(trophy_changes, dict):
                for pid, delta in trophy_changes.items():
                    sign = "+" if delta >= 0 else ""
                    result_lines.append(f"🏅 <@{pid}>: {sign}{delta} trophies")
            elif cpu_trophy_change is not None:
                sign = "+" if cpu_trophy_change >= 0 else ""
                result_lines.append(f"🏅 Trophy change: {sign}{cpu_trophy_change}")
            if coin_reward:
                result_lines.append(f"💰 Reward: +{coin_reward} coins")

            embed_a.description = "─" * 32 + "\n" + "\n".join(result_lines) + "\n" + "─" * 32 + "\n\n" + (embed_a.description or "")
            embed_c_log = make_embed(None, "Battle Log \u2014 Ended", log_text[:1024] if log_text else "\u2014", color=0x2b2d31)
            return embed_a, embed_b, embed_c_log, None

        offensive, defensive = self._fighter_attack_rows(data, battle_id, turn_user)
        switch_opts = self._switch_options(data, battle_id, turn_user)

        atk_emoji = {"normal": e("attack_normal",data), "special": e("attack_special",data), "ultimate": e("attack_ultimate",data), "unique_skill": e("attack_unique_skill",data), "unique_path": e("attack_unique_path",data)}
        attack_opts: list[discord.SelectOption] = []
        for r in offensive:
            nt = normalize_attack_type(str(r.get("type", "normal")))
            if nt not in {"normal", "special", "ultimate", "unique_skill", "unique_path"}:
                continue
            power = r.get("power")
            left = int(r.get("left", -1))
            uses = "∞" if left == -1 else str(left)
            desc = f"{nt.replace('_', ' ').title()} • Power {power if power is not None else '?'} • Uses {uses}"
            attack_opts.append(discord.SelectOption(
                label=r.get("name", "Move")[:100],
                value=str(r.get("key", "")),
                description=desc[:100],
                emoji=option_emoji(atk_emoji.get(nt, e("common", data))),
            ))
        attack_opts = attack_opts[:25]

        defense_icon = {"block": e("def_block",data), "dodge": e("def_dodge",data), "revert": e("def_revert",data), "parry": e("def_parry",data), "tank": e("def_tank",data)}
        defense_opts = []
        for r in defensive[:25]:
            nt = normalize_attack_type(str(r.get("type", "defense")))
            left = int(r.get("left", -1))
            uses = "∞" if left == -1 else str(left)
            defense_opts.append(discord.SelectOption(
                label=r.get("name", "Defense")[:100],
                value=str(r.get("key", "")),
                description=f"{nt.title()} • Uses {uses}"[:100],
                emoji=option_emoji(defense_icon.get(nt, '🛡️')),
            ))
        sw_opts = [discord.SelectOption(label=o.label, value=str(o.value), description=o.description, emoji=getattr(o, "emoji", None), default=getattr(o, "default", False)) for o in switch_opts][:25]

        turn_state = players.get(turn_user, {}) if isinstance(players.get(turn_user), dict) else {}
        view = TurnView(self, battle_id, turn_user, attack_opts, defense_opts, sw_opts, enemy_id=b_id if turn_user == a_id else a_id)
        if isinstance(turn_state, dict) and bool(turn_state.get("is_cpu", False)):
            for item in view.children:
                item.disabled = True
        return embed_a, embed_b, embed_c, view

    def _active_turn_card_image(self, data: dict[str, Any], battle_id: str) -> tuple[str | None, str | None]:
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return None, None
        turn_user = str(battle.get("turn_user_id", ""))
        players = battle.get("players", {}) if isinstance(battle.get("players", {}), dict) else {}
        pstate = players.get(turn_user, {}) if isinstance(players.get(turn_user, {}), dict) else {}
        uid = self._current_uid(pstate) if isinstance(pstate, dict) else ""
        fighter_names = pstate.get("fighter_names", {}) if isinstance(pstate.get("fighter_names"), dict) else {}
        card_name = str(fighter_names.get(uid, ""))
        cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
        card_def = cards.get(card_name, {}) if isinstance(cards.get(card_name, {}), dict) else {}
        return card_image_url(card_def), card_name or None

    async def _send_battle_stats_embed(self, channel: Any, battle: dict) -> None:
        """Post the post-battle summary embed to the given channel."""
        try:
            players: dict = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
            winner_id = str(battle.get("winner_id", ""))
            winner_state = players.get(winner_id, {}) if isinstance(players.get(winner_id), dict) else {}
            if winner_id and isinstance(winner_state, dict) and bool(winner_state.get("is_cpu", False)):
                cpu_meta = winner_state.get("cpu_meta", {}) or {}
                winner_name = str(cpu_meta.get("display_name", "🤖 CPU")) if isinstance(cpu_meta, dict) else "🤖 CPU"
            elif winner_id:
                winner_name = f"<@{winner_id}>"
            else:
                winner_name = "—"
            stats_embed = build_battle_stats_embed(battle, winner_name)
            if hasattr(channel, "send"):
                await channel.send(embed=stats_embed)
        except Exception:
            logger.exception("[BATTLE_STATS] failed to send stats embed")

    async def _refresh_battle_message(self, battle_id: str) -> None:
        data = self.bot.storage.load()
        battle = self._lookup_battle(data, battle_id)
        if not isinstance(battle, dict):
            return
        channel_id = int(str(battle.get("message_channel_id", "0")) or 0)
        message_id = int(str(battle.get("message_id", "0")) or 0)
        if not channel_id or not message_id:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            return
        try:
            msg = await channel.fetch_message(message_id)
        except Exception:
            logger.exception("[BATTLE_REFRESH] failed to fetch message battle_id=%s channel=%s message=%s", battle_id, channel_id, message_id)
            return

        embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
        if view is not None:
            style_view(view, data)
        try:
            await msg.edit(embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view, attachments=[])
        except Exception:
            logger.exception("[BATTLE_REFRESH] failed to edit message battle_id=%s channel=%s message=%s", battle_id, channel_id, message_id)

        # Send stats summary once when the battle is freshly over
        if bool(battle.get("ended", False)) and not bool(battle.get("stats_sent", False)):
            def _mark_stats_sent(data: dict) -> None:
                b = self._battle_root(data).get("recently_ended")
                if isinstance(b, list):
                    for entry in b:
                        if isinstance(entry, dict) and str(entry.get("battle_id", "")) == battle_id:
                            entry["stats_sent"] = True
                            return
            self.bot.storage.with_lock(_mark_stats_sent)
            await self._send_battle_stats_embed(channel, battle)

    def _schedule_timeout(self, battle_id: str) -> None:
        old = self.turn_tasks.get(battle_id)
        current_task = asyncio.current_task()
        if old and old is not current_task and not old.done():
            old.cancel()

        async def waiter() -> None:
            await asyncio.sleep(TURN_TIMEOUT_SECONDS)

            def mutate(data: dict[str, Any]) -> dict[str, Any]:
                battle = self._battle_root(data).get("active", {}).get(battle_id)
                if not isinstance(battle, dict) or bool(battle.get("ended", False)):
                    return {"ok": False}
                ts = int(battle.get("turn_started_at", 0))
                if now_ts() - ts < TURN_TIMEOUT_SECONDS:
                    return {"ok": False}
                # Auto-attack with normal or defensive instead of skipping
                actor = str(battle.get("turn_user_id", ""))
                if not actor:
                    return {"ok": False}
                players = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
                pstate = players.get(actor)
                if isinstance(pstate, dict) and bool(pstate.get("is_cpu", False)):
                    return {"ok": False}  # CPU handles its own turns
                enemy_id = next((str(pid) for pid in players.keys() if str(pid) != actor), "")
                if not enemy_id:
                    return {"ok": False}

                # Auto-execute a normal attack only (no defense)
                offensive, _defensive = self._fighter_attack_rows(data, battle_id, actor)
                auto_move = None
                auto_value = None
                for row in offensive:
                    if normalize_attack_type(str(row.get("type", "normal"))) == "normal" and int(row.get("left", -1)) != 0:
                        auto_move = "normal"
                        auto_value = str(row.get("key", "normal"))
                        break

                if auto_move and auto_value:
                    result = apply_move(data, battle_id, actor, auto_move, auto_value)
                    if result.get("ok"):
                        battle.setdefault("log", []).append(f"⏱ {actor} auto-{auto_move.upper()}")
                        return result

                # Fallback: just skip turn
                has_cpu = any(isinstance(ps, dict) and bool(ps.get("is_cpu", False)) for ps in players.values())
                idle_skips = battle.setdefault("idle_skip_counts", {})
                if not isinstance(idle_skips, dict):
                    idle_skips = {}
                    battle["idle_skip_counts"] = idle_skips
                actor_idle_count = int(idle_skips.get(actor, 0) or 0) + 1
                idle_skips[actor] = actor_idle_count
                idle_skips[enemy_id] = 0

                battle.setdefault("log", []).append(f"⏭ {actor} skipped their turn")

                if has_cpu and actor_idle_count >= IDLE_SKIP_LIMIT_VS_CPU:
                    battle.setdefault("log", []).append("Battle ended due to player inactivity.")
                    return end_battle(data, battle_id, "", "", "timeout_abandoned")

                battle["turn_user_id"] = enemy_id
                battle["turn_started_at"] = now_ts()
                battle["round"] = int(battle.get("round", 1)) + 1
                return {"ok": True, "skipped": True}

            result = self.bot.storage.with_lock(mutate)
            if result.get("ok"):
                await self.bot.battle_service.sync_active_by_user_from_data(self.bot.storage.load())
                await self._refresh_battle_message(battle_id)
                if result.get("battle_over"):
                    logger.info("[TURN_TIMEOUT] ended battle_id=%s reason=%s", battle_id, result.get("reason", "unknown"))
                    self._cancel_battle_runtime_tasks(battle_id)
                    return
                logger.info("[TURN_TIMEOUT] advanced battle_id=%s skipped=%s", battle_id, bool(result.get("skipped", False)))
                self._schedule_timeout(battle_id)
                await self._maybe_run_cpu_turn(battle_id)

        self._track_background_task(
            self.turn_tasks,
            battle_id,
            asyncio.create_task(waiter()),
            "turn_timeout",
        )
        data = self.bot.storage.load()
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        turn_user = str(battle.get("turn_user_id", "")) if isinstance(battle, dict) else ""
        logger.info("[TURN_TIMEOUT] scheduled battle_id=%s turn_user=%s timeout=%ss", battle_id, turn_user, TURN_TIMEOUT_SECONDS)
        # E. Live turn timer: cancel any existing timer task and start a fresh one
        old_timer = self.timer_tasks.pop(str(battle_id), None)
        if old_timer and not old_timer.done():
            old_timer.cancel()
        self._track_background_task(
            self.timer_tasks,
            battle_id,
            asyncio.create_task(self._tick_timer(battle_id, TURN_TIMEOUT_SECONDS)),
            "turn_timer",
        )
        self._schedule_cpu_stall_watchdog(battle_id)

    def _schedule_cpu_stall_watchdog(self, battle_id: str) -> None:
        old = self.battle_stall_tasks.get(battle_id)
        current_task = asyncio.current_task()
        if old and old is not current_task and not old.done():
            old.cancel()

        data = self.bot.storage.load()
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return
        players = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
        if not any(isinstance(p, dict) and bool(p.get("is_cpu", False)) for p in players.values()):
            return

        turn_snapshot = int(battle.get("turn_started_at", 0))

        async def watchdog() -> None:
            await asyncio.sleep(CPU_STALL_TIMEOUT_SECONDS)

            def mutate(d: dict[str, Any]) -> dict[str, Any]:
                b = self._battle_root(d).get("active", {}).get(battle_id)
                if not isinstance(b, dict) or bool(b.get("ended", False)):
                    return {"ok": False}
                if int(b.get("turn_started_at", 0)) != turn_snapshot:
                    return {"ok": False}
                players_now = b.get("players", {}) if isinstance(b.get("players"), dict) else {}
                if not any(isinstance(p, dict) and bool(p.get("is_cpu", False)) for p in players_now.values()):
                    return {"ok": False}
                current = str(b.get("turn_user_id", ""))
                if not current:
                    return {"ok": False}
                loser = current
                winner = next((str(pid) for pid in players_now.keys() if str(pid) != current), "")
                if not winner:
                    return {"ok": False}
                return end_battle(d, battle_id, "", "", "timeout_abandoned")

            result = self.bot.storage.with_lock(mutate)
            if result.get("ok"):
                await self.bot.battle_service.sync_active_by_user_from_data(self.bot.storage.load())
                await self._refresh_battle_message(battle_id)
                logger.info("[CPU_STALL] ended battle_id=%s reason=%s", battle_id, result.get("reason", "unknown"))
                self._cancel_battle_runtime_tasks(battle_id)

        self._track_background_task(
            self.battle_stall_tasks,
            battle_id,
            asyncio.create_task(watchdog()),
            "cpu_stall_watchdog",
        )

    async def _start_battle(self, channel: discord.abc.Messageable, battle_id: str) -> None:
        data = self.bot.storage.load()
        embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
        try:
            if view is not None:
                style_view(view, data)
            msg = await channel.send(embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)
            if view is not None and hasattr(view, "message"):
                view.message = msg
        except Exception:
            logger.error("[BATTLE_UI] failed to send for battle_id=%s\n%s", battle_id, traceback.format_exc())
            raise

        def mutate(state: dict[str, Any]) -> None:
            battle = self._battle_root(state).get("active", {}).get(battle_id)
            if isinstance(battle, dict):
                battle["message_channel_id"] = str(msg.channel.id)
                battle["message_id"] = str(msg.id)

        self.bot.storage.with_lock(mutate)
        self._schedule_timeout(battle_id)
        await self._maybe_run_cpu_turn(battle_id)

    def choose_cpu_move(self, data: dict[str, Any], battle_id: str, cpu_id: str, enemy_id: str) -> tuple[str, str]:
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return "normal", "normal"

        cpu_state = (battle.get("players", {}) or {}).get(cpu_id, {})
        enemy_state = (battle.get("players", {}) or {}).get(enemy_id, {})
        offensive, defensive = self._fighter_attack_rows(data, battle_id, cpu_id)
        enemy_offensive, _enemy_defensive = self._fighter_attack_rows(data, battle_id, enemy_id)
        personality = str((cpu_state.get("cpu_meta", {}) or {}).get("personality", "Balanced")) if isinstance(cpu_state, dict) else "Balanced"
        cpu_uid = self._current_uid(cpu_state) if isinstance(cpu_state, dict) else ""
        ene_uid = self._current_uid(enemy_state) if isinstance(enemy_state, dict) else ""

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
    async def _maybe_run_cpu_turn(self, battle_id: str) -> None:
        data = self.bot.storage.load()
        battle = self._battle_root(data).get("active", {}).get(battle_id)
        if not isinstance(battle, dict):
            return
        turn_user = str(battle.get("turn_user_id", ""))
        players = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
        cpu_state = players.get(turn_user)
        if not isinstance(cpu_state, dict) or not bool(cpu_state.get("is_cpu", False)):
            return
        enemy_id = next((str(pid) for pid in players.keys() if str(pid) != turn_user), "")
        if not enemy_id:
            return
        await asyncio.sleep(random.uniform(0.3, 0.8))

        def force_cpu_skip(d: dict[str, Any]) -> dict[str, Any]:
            b = self._battle_root(d).get("active", {}).get(battle_id)
            if not isinstance(b, dict):
                return {"ok": False, "error": "battle_not_found"}
            if bool(b.get("ended", False)):
                return {"ok": False, "error": "battle_already_ended"}
            players_now = b.get("players", {}) if isinstance(b.get("players"), dict) else {}
            current = str(b.get("turn_user_id", ""))
            if not current:
                return {"ok": False, "error": "not_cpu_turn"}
            next_id = next((str(pid) for pid in players_now.keys() if str(pid) != current), "")
            if not next_id:
                return {"ok": False, "error": "not_cpu_turn"}
            b["turn_user_id"] = next_id
            b["turn_started_at"] = now_ts()
            b["round"] = int(b.get("round", 1)) + 1
            b.setdefault("log", []).append(f"⏭ {current} skipped their turn")
            return {"ok": True, "skipped": True}

        def mutate(d: dict[str, Any]) -> dict[str, Any]:
            def conservative_fallback_move() -> tuple[str, str] | None:
                battle_now = self._battle_root(d).get("active", {}).get(battle_id)
                if not isinstance(battle_now, dict):
                    return None
                players_now = battle_now.get("players", {}) if isinstance(battle_now.get("players"), dict) else {}
                ai_now = players_now.get(turn_user) if isinstance(players_now.get(turn_user), dict) else None
                if not isinstance(ai_now, dict):
                    return None
                ai_uid_now = self._resolve_active_uid(ai_now)
                if ai_uid_now is None:
                    return None

                side_last_group_now = str((battle_now.get("last_move_group_by_side", {}) or {}).get(turn_user, "")) if isinstance(battle_now.get("last_move_group_by_side", {}), dict) else ""
                if not side_last_group_now:
                    side_last_group_now = str((battle_now.get("last_move_group_by_char_uid", {}) or {}).get(ai_uid_now, "")) if isinstance(battle_now.get("last_move_group_by_char_uid", {}), dict) else ""
                special_allowed_now = side_last_group_now != "special_like"

                offensive_now, defensive_now = self._fighter_attack_rows(d, battle_id, turn_user)
                for row in offensive_now:
                    if normalize_attack_type(str(row.get("type", "normal"))) == "normal":
                        return "normal", str(row.get("key", "normal"))
                if special_allowed_now:
                    for row in offensive_now:
                        typ = normalize_attack_type(str(row.get("type", "normal")))
                        if typ in {"special", "ultimate", "unique_skill", "unique_path"}:
                            return typ, str(row.get("key", typ))
                for row in defensive_now:
                    typ = normalize_attack_type(str(row.get("type", "block")))
                    if typ in {"block", "dodge", "revert", "parry", "tank"}:
                        return typ, str(row.get("key", typ))
                switch_opts_now = self._switch_options(d, battle_id, turn_user)
                if switch_opts_now:
                    return "switch", str(switch_opts_now[0].value)
                return None

            try:
                b = self._battle_root(d).get("active", {}).get(battle_id)
                if not isinstance(b, dict):
                    return {"ok": False, "error": "battle_not_found"}
                players_now = b.get("players", {}) if isinstance(b.get("players"), dict) else {}
                ai_state = players_now.get(turn_user) if isinstance(players_now.get(turn_user), dict) else None
                opp_id = next((str(pid) for pid in players_now.keys() if str(pid) != turn_user), "")
                opp_state = players_now.get(opp_id) if isinstance(players_now.get(opp_id), dict) else None
                if bool(b.get("ended", False)):
                    return {"ok": False, "error": "battle_already_ended"}
                if str(b.get("turn_user_id", "")) != turn_user:
                    return {"ok": False, "error": "not_cpu_turn"}
                ai_uid = self._resolve_active_uid(ai_state if isinstance(ai_state, dict) else {})
                logger.debug("[AI] resolved_active_card=%s", ai_uid or "None")
                if ai_uid is None:
                    return end_battle(d, battle_id, opp_id, turn_user, "no_active_fighter")
                if isinstance(opp_state, dict) and self._resolve_active_uid(opp_state) is None:
                    return end_battle(d, battle_id, turn_user, opp_id, "no_active_fighter")
                try:
                    move_type, move_value = self.choose_cpu_move(d, battle_id, turn_user, enemy_id)
                except Exception:
                    logger.exception("[AI_TURN] cpu decision failed battle_id=%s", battle_id)
                    return force_cpu_skip(d)
                if str(move_type).strip().lower() == "skip":
                    return force_cpu_skip(d)
                result = apply_move(d, battle_id, turn_user, str(move_type), str(move_value))
                if not result.get("ok"):
                    fallback = conservative_fallback_move()
                    if fallback is not None:
                        fallback_type, fallback_value = fallback
                        if str(fallback_type).strip().lower() == "skip":
                            return force_cpu_skip(d)
                        retry_result = apply_move(d, battle_id, turn_user, str(fallback_type), str(fallback_value))
                        if retry_result.get("ok"):
                            b2 = self._battle_root(d).get("active", {}).get(battle_id)
                            if isinstance(b2, dict):
                                json_safe_battle_state(b2)
                            return retry_result
                if not result.get("ok"):
                    logger.warning("[AI_TURN] cpu action failed battle_id=%s move=%s reason=%s", battle_id, move_type, result.get("error", "unknown"))
                    return force_cpu_skip(d)
                b2 = self._battle_root(d).get("active", {}).get(battle_id)
                if isinstance(b2, dict):
                    json_safe_battle_state(b2)
                return result
            except Exception:
                logger.exception("[AI_TURN] cpu turn failed battle_id=%s", battle_id)
                return {"ok": False, "error": "cpu_turn_failed"}

        result = self.bot.storage.with_lock(mutate)
        if result.get("ok"):
            await self.bot.battle_service.sync_active_by_user_from_data(self.bot.storage.load())
            await self._refresh_battle_message(battle_id)
            if result.get("battle_over"):
                logger.info("[AI_TURN] ended battle_id=%s reason=%s", battle_id, result.get("reason", "unknown"))
                self._cancel_battle_runtime_tasks(battle_id)
                return
            logger.info("[AI_TURN] advanced battle_id=%s skipped=%s", battle_id, bool(result.get("skipped", False)))
            self._schedule_timeout(battle_id)
            await self._maybe_run_cpu_turn(battle_id)
        else:
            logger.warning("[AI_TURN] skipped battle_id=%s reason=%s", battle_id, result.get("error", "unknown"))

    async def open_attack_picker(self, interaction: discord.Interaction, battle_id: str, actor_id: str, category: str | None = None) -> None:
        data = self.bot.storage.load()
        embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
        await self._apply_battle_message_update(interaction, embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)

    async def open_defense_picker(self, interaction: discord.Interaction, battle_id: str, actor_id: str) -> None:
        data = self.bot.storage.load()
        embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
        await self._apply_battle_message_update(interaction, embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)

    async def open_switch_picker(self, interaction: discord.Interaction, battle_id: str, actor_id: str) -> None:
        data = self.bot.storage.load()
        embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
        await self._apply_battle_message_update(interaction, embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)

    async def _post_action_update(self, interaction: discord.Interaction, battle_id: str) -> None:
        data = self.bot.storage.load()
        battle = self._lookup_battle(data, battle_id)
        ended = isinstance(battle, dict) and bool(battle.get("ended", False))
        # Sync active_by_user so user can queue again after battle ends.
        await self.bot.battle_service.sync_active_by_user_from_data(data)

        # ── Parse last log entry for damage/attacker info (used for animations) ──
        last_damage = 0
        attacker_display = "fighter"
        hp_override_mid: dict[str, int] = {}
        if not ended and isinstance(battle, dict):
            logs = battle.get("log", [])
            if logs:
                last_entry = str(logs[-1])
                parts = last_entry.split(":", 2)
                if len(parts) == 3:
                    pid_raw, _move_raw, dmg_raw = parts[0].strip(), parts[1].strip(), parts[2].strip()
                    try:
                        last_damage = int(dmg_raw)
                    except (ValueError, TypeError):
                        last_damage = 0
                    # Build attacker display label
                    if pid_raw.isdigit():
                        attacker_display = f"<@{pid_raw}>"
                    elif pid_raw:
                        attacker_display = pid_raw
                    # Compute mid-HP for damaged side (opponent of attacker)
                    if last_damage > 0:
                        players_map = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
                        for other_pid, other_state in players_map.items():
                            if str(other_pid) != pid_raw and isinstance(other_state, dict):
                                other_uid = self._current_uid(other_state)
                                if other_uid:
                                    hp_map = other_state.get("hp", {}) if isinstance(other_state.get("hp"), dict) else {}
                                    cur = int(hp_map.get(other_uid, 0))
                                    mid = cur + last_damage // 2
                                    hp_override_mid[other_uid] = mid

        # Build final embeds (with real HP values)
        embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)

        # ── Battle animations (only for ongoing battles with a live message) ──
        msg = getattr(interaction, "message", None)
        if not ended and msg is not None:
            # B. Turn transition: show "winds up..." before the result
            try:
                transition_embed = make_embed(None, f"{e('list', data)} Battle Log", f"> {attacker_display} winds up...", color=0x2b2d31)
                pre_embeds = [emb for emb in (embed_a, embed_b, transition_embed) if emb is not None]
                await msg.edit(embeds=pre_embeds)
                await asyncio.sleep(0.7)
            except Exception:
                pass

            # D. Hit flash: briefly turn embed color red when damage was dealt
            if last_damage > 0:
                try:
                    for emb in [embed_a, embed_b]:
                        if emb is not None:
                            emb.color = discord.Color(0xe53935)
                    flash_embeds = [emb for emb in (embed_a, embed_b, transition_embed) if emb is not None]
                    await msg.edit(embeds=flash_embeds)
                    await asyncio.sleep(0.6)
                    for emb in [embed_a, embed_b]:
                        if emb is not None:
                            emb.color = discord.Color(0x2b2d31)
                except Exception:
                    pass

            # C. HP drain animation: show mid-HP step before final HP
            if last_damage > 0 and hp_override_mid:
                try:
                    embed_a_mid, embed_b_mid, embed_c_mid, _ = self._build_embed_view(data, battle_id, display_hp_override=hp_override_mid)
                    mid_embeds = [emb for emb in (embed_a_mid, embed_b_mid, embed_c_mid) if emb is not None]
                    await msg.edit(embeds=mid_embeds)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

        await self._apply_battle_message_update(interaction, embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)
        if ended:
            logger.info("[TURN_FLOW] battle ended battle_id=%s reason=%s", battle_id, battle.get("reason", "unknown") if isinstance(battle, dict) else "unknown")
            self._cancel_battle_runtime_tasks(battle_id)
            # Send the battle stats summary if not already sent
            if isinstance(battle, dict) and not bool(battle.get("stats_sent", False)):
                def _mark_stats_sent_post(d: dict) -> None:
                    for entry in d.get("battle", {}).get("recently_ended", []):
                        if isinstance(entry, dict) and str(entry.get("battle_id", "")) == battle_id:
                            entry["stats_sent"] = True
                            return
                self.bot.storage.with_lock(_mark_stats_sent_post)
                channel = getattr(interaction, "channel", None)
                if channel is None:
                    try:
                        channel = await interaction.original_response()
                        channel = getattr(channel, "channel", None)
                    except Exception:
                        channel = None
                if channel is not None:
                    await self._send_battle_stats_embed(channel, battle)
            return
        self._schedule_timeout(battle_id)
        await self._maybe_run_cpu_turn(battle_id)

    async def resolve_selected_attack(self, interaction: discord.Interaction, battle_id: str, actor_id: str, attack_key: str) -> None:
        def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            ensure_attacks_structure(data)
            battle = self._battle_root(data).get("active", {}).get(battle_id)
            if not isinstance(battle, dict):
                return {"ok": False, "error": "battle_not_found"}, {}

            pstate = (battle.get("players", {}) or {}).get(actor_id)
            if not isinstance(pstate, dict):
                return {"ok": False, "error": "not_in_battle"}, {}

            players = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
            actor_state = players.get(actor_id) if isinstance(players.get(actor_id), dict) else None
            enemy_id_chk = next((str(pid) for pid in players.keys() if str(pid) != actor_id), "")
            enemy_state_chk = players.get(enemy_id_chk) if isinstance(players.get(enemy_id_chk), dict) else None
            actor_uid_chk = self._resolve_active_uid(actor_state if isinstance(actor_state, dict) else {})
            enemy_uid_chk = self._resolve_active_uid(enemy_state_chk if isinstance(enemy_state_chk, dict) else {})
            if actor_uid_chk is None:
                return {"ok": False, "error": "no_active_fighter"}, {}
            if enemy_id_chk and enemy_uid_chk is None:
                return end_battle(data, battle_id, actor_id, enemy_id_chk, "no_active_fighter"), {}

            # Check what type of move is being selected before enforcing turn
            offensive, defensive = self._fighter_attack_rows(data, battle_id, actor_id)
            chosen = None
            selected_norm = str(attack_key)

            for row in offensive + defensive:
                r_norm = normalize_attack_type(str(row.get("type", "normal")))
                if str(row.get("key", "")) == selected_norm or r_norm == selected_norm:
                    chosen = row
                    break

            if chosen is None:
                return {"ok": False, "error": "attack_missing"}, {}

            # Defence can be pre-selected any time by either player
            # Offensive/switch moves require it to be your turn
            chosen_norm = normalize_attack_type(str(chosen.get("type", "normal")))
            is_defence_move = chosen_norm in {"block", "dodge", "revert", "parry", "tank"}
            if not is_defence_move and str(battle.get("turn_user_id", "")) != actor_id:
                return {"ok": False, "error": "not_your_turn"}, {}

            key = str(chosen.get("key", ""))
            uid = self._current_uid(pstate)
            uses_map = pstate.setdefault("attack_uses", {}).setdefault(uid, {})
            left = int(chosen.get("left", -1))
            if left == 0:
                return {"ok": False, "error": "no_uses_left"}, {}

            normalized = normalize_attack_type(str(chosen.get("type", "normal")))

            if is_defence_move and str(battle.get("turn_user_id", "")) != actor_id:
                used_defs = battle.setdefault("used_defenses_by_char_uid", {})
                if not isinstance(used_defs, dict):
                    used_defs = {}
                    battle["used_defenses_by_char_uid"] = used_defs
                raw_used = used_defs.get(uid, set())
                if isinstance(raw_used, set):
                    used_set = raw_used
                elif isinstance(raw_used, list):
                    used_set = {str(x) for x in raw_used}
                else:
                    used_set = set()
                if normalized in used_set:
                    return {"ok": False, "error": "defense_already_used"}, {}
                used_set.add(normalized)
                used_defs[uid] = used_set

                pending = battle.setdefault("pending_defense_by_char_uid", {})
                if not isinstance(pending, dict):
                    pending = {}
                    battle["pending_defense_by_char_uid"] = pending
                pending[uid] = normalized

                battle.setdefault("last_move_group_by_char_uid", {})[uid] = "normal_or_defensive"
                battle.setdefault("last_move_group_by_side", {})[actor_id] = "normal_or_defensive"
                battle.setdefault("log", []).append(f"{actor_id} prepares {normalized.upper()}")
                if left > 0:
                    uses_map[key] = left - 1
                json_safe_battle_state(battle)
                return {"ok": True, "success": True}, {"type": normalized, "name": str(chosen.get("name", ""))}

            result = apply_move(data, battle_id, actor_id, normalized, key)
            if result.get("ok") and left > 0:
                uses_map[key] = left - 1

            updated_battle = self._battle_root(data).get("active", {}).get(battle_id)
            if isinstance(updated_battle, dict):
                json_safe_battle_state(updated_battle)

            return result, {"type": normalized, "name": str(chosen.get("name", ""))}

        # A. Typing indicator during damage calculation
        _channel = getattr(interaction, "channel", None)
        if _channel is not None:
            async with _channel.typing():
                result, _detail = self.bot.storage.with_lock(mutate)
                data = self.bot.storage.load()
        else:
            result, _detail = self.bot.storage.with_lock(mutate)
            data = self.bot.storage.load()
        if not result.get("ok"):
            await battle_warn(interaction, make_embed(data, f"{e('warning', data)} Move Failed", battle_error_text(result.get("error", "unknown"))))
            # Try to refresh - but if view is None, keep existing buttons
            try:
                embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
                if view is not None:
                    await self._apply_battle_message_update(interaction, embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)
            except Exception:
                logger.exception("Failed to refresh battle embed after action")
            return

        def clear_idle(data: dict[str, Any]) -> None:
            battle = self._battle_root(data).get("active", {}).get(battle_id)
            if not isinstance(battle, dict):
                return
            idle_skips = battle.get("idle_skip_counts")
            if isinstance(idle_skips, dict):
                idle_skips[actor_id] = 0

        self.bot.storage.with_lock(clear_idle)
        await self._post_action_update(interaction, battle_id)

    async def resolve_move(self, interaction: discord.Interaction, battle_id: str, actor_id: str, move_type: str, value: str | None) -> None:
        def mutate(d: dict[str, Any]) -> dict[str, Any]:
            battle = self._battle_root(d).get("active", {}).get(battle_id)
            if not isinstance(battle, dict):
                return {"ok": False, "error": "battle_not_found"}
            if str(battle.get("turn_user_id", "")) != actor_id:
                return {"ok": False, "error": "not_your_turn"}

            updated = self._battle_root(d).get("active", {}).get(battle_id)
            if str(move_type).lower() == "switch":
                if not isinstance(updated, dict):
                    return {"ok": False, "error": "battle_not_found"}
                players = updated.get("players", {}) if isinstance(updated.get("players"), dict) else {}
                me_state = players.get(actor_id) if isinstance(players.get(actor_id), dict) else None
                target_idx = self._resolve_switch_target_index(me_state if isinstance(me_state, dict) else {}, value)
                if target_idx is None:
                    return {"ok": False, "error": "invalid_switch"}
                result = self._apply_switch(updated, actor_id, target_idx)
            else:
                result = apply_move(d, battle_id, actor_id, move_type, value)
            updated = self._battle_root(d).get("active", {}).get(battle_id)
            if isinstance(updated, dict):
                json_safe_battle_state(updated)
            return result

        # A. Typing indicator during damage calculation
        _channel_mv = getattr(interaction, "channel", None)
        if _channel_mv is not None:
            async with _channel_mv.typing():
                result = self.bot.storage.with_lock(mutate)
                data = self.bot.storage.load()
        else:
            result = self.bot.storage.with_lock(mutate)
            data = self.bot.storage.load()
        if not result.get("ok"):
            await battle_warn(interaction, make_embed(data, f"{e('warning', data)} Move Failed", battle_error_text(result.get("error", "unknown"))))
            # Try to refresh - but if view is None, keep existing buttons
            try:
                embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
                if view is not None:
                    await self._apply_battle_message_update(interaction, embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None], view=view)
            except Exception:
                logger.exception("Failed to refresh battle embed after action")
            return

        def clear_idle(data: dict[str, Any]) -> None:
            battle = self._battle_root(data).get("active", {}).get(battle_id)
            if not isinstance(battle, dict):
                return
            idle_skips = battle.get("idle_skip_counts")
            if isinstance(idle_skips, dict):
                idle_skips[actor_id] = 0

        self.bot.storage.with_lock(clear_idle)
        logger.info("[TURN_FLOW] entering auto-advance after %s", str(move_type).lower())
        await self._post_action_update(interaction, battle_id)

    def _rollback_battle_for_users(self, data: dict[str, Any], user_ids: set[str]) -> int:
        root = self._battle_root(data)
        active = root.get("active", {})
        if not isinstance(active, dict):
            return 0
        removed = 0
        for bid, battle in list(active.items()):
            if not isinstance(battle, dict):
                continue
            players = battle.get("players", {})
            if not isinstance(players, dict):
                continue
            pset = {str(x) for x in players.keys()}
            if pset & user_ids:
                active.pop(bid, None)
                removed += 1
        return removed

    async def start_battle_or_fail(self, interaction: discord.Interaction, challenger_id: str, opponent_id: str, mode: str, *, clear_pending_target_id: str | None = None, cpu_opponent: dict[str, Any] | None = None) -> tuple[bool, str]:
        now = now_ts()

        def mutate_create(data: dict[str, Any]) -> dict[str, Any]:
            self._cleanup_expired(data)
            cid = str(challenger_id)
            oid = str(opponent_id)
            if not cid or not oid:
                return {"ok": False, "error": "missing_data"}
            if cid == oid:
                return {"ok": False, "error": "invalid_participants"}
            if not get_player(data, cid):
                return {"ok": False, "error": "missing_data"}
            if not cpu_opponent and not get_player(data, oid):
                return {"ok": False, "error": "missing_data"}
            if self._active_battle_id(data, cid) or (not cpu_opponent and self._active_battle_id(data, oid)):
                return {"ok": False, "error": "already_active"}

            team_a = self._snapshot_team(data, cid)
            team_b = self._snapshot_team(data, oid) if not cpu_opponent else list(team_a)
            if not team_a or not team_b:
                return {"ok": False, "error": "missing_squad"}

            root = self._battle_root(data)
            queue = root.get("queue", [])
            if isinstance(queue, list):
                root["queue"] = [q for q in queue if not (isinstance(q, dict) and str(q.get("user_id", "")) in {cid, oid})]

            if clear_pending_target_id:
                pending = root.get("pending_friendly", {})
                if isinstance(pending, dict):
                    pending.pop(str(clear_pending_target_id), None)

            bid = create_battle_state(data, mode, cid, oid, team_a, team_b, now, participant_a=None, participant_b=cpu_opponent)
            self._init_attack_uses_for_battle(data, bid)
            return {"ok": True, "battle_id": bid}

        created = self.bot.storage.with_lock(mutate_create)
        if not created.get("ok"):
            reason = str(created.get("error", "unknown"))
            logger.warning("[BATTLE_START] failed prestart mode=%s c=%s o=%s reason=%s", mode, challenger_id, opponent_id, reason)
            return False, reason

        battle_id = str(created.get("battle_id", ""))
        if not battle_id:
            return False, "missing_data"
        await self.bot.battle_service.remove_queue_users([str(challenger_id), str(opponent_id)])
        if clear_pending_target_id:
            await self.bot.battle_service.remove_pending_friendly(str(clear_pending_target_id))
        await self.bot.battle_service.sync_active_by_user_from_data(self.bot.storage.load())

        try:
            if interaction.channel is None:
                raise RuntimeError("missing_channel")
            await self._start_battle(interaction.channel, battle_id)
            logger.info("[BATTLE_START] success mode=%s battle_id=%s c=%s o=%s", mode, battle_id, challenger_id, opponent_id)
            return True, "ok"
        except Exception as exc:
            logger.exception("[BATTLE_START] failed mode=%s battle_id=%s c=%s o=%s", mode, battle_id, challenger_id, opponent_id)

            def mutate_rollback(data: dict[str, Any]) -> None:
                users = {str(challenger_id), str(opponent_id)}
                self._rollback_battle_for_users(data, users)
                if clear_pending_target_id:
                    pending = self._battle_root(data).get("pending_friendly", {})
                    if isinstance(pending, dict):
                        pending.pop(str(clear_pending_target_id), None)

            self.bot.storage.with_lock(mutate_rollback)
            await self.bot.battle_service.sync_active_by_user_from_data(self.bot.storage.load())
            return False, f"start_failed: {type(exc).__name__}"

    async def _try_match(self, interaction: discord.Interaction, user_id: str) -> bool:
        def mutate_pick(data: dict[str, Any]) -> dict[str, Any]:
            root = self._battle_root(data)
            self._cleanup_expired(data)
            queue = root.get("queue", [])
            if not isinstance(queue, list):
                root["queue"] = []
                queue = root["queue"]

            me = next((x for x in queue if isinstance(x, dict) and str(x.get("user_id", "")) == user_id), None)
            if not isinstance(me, dict):
                return {"ok": False, "error": "not_queued"}

            my_trophy = self._player_trophies(data, user_id)

            # Adaptive trophy bracket: ±200 at t=0, +100 every 30s queued, capped at ±2000.
            now = now_ts()
            def _window(joined_at: int) -> int:
                elapsed = max(0, now - int(joined_at))
                return min(2000, 200 + (elapsed // 30) * 100)

            my_window = _window(int(me.get("joined_at", now)))

            target = None
            for q in queue:
                if not isinstance(q, dict):
                    continue
                uid = str(q.get("user_id", ""))
                if uid == user_id:
                    continue
                window = max(my_window, _window(int(q.get("joined_at", now))))
                if abs(my_trophy - self._player_trophies(data, uid)) <= window:
                    target = q
                    break
            if not isinstance(target, dict):
                return {"ok": False, "error": "no_match"}

            return {"ok": True, "opp_id": str(target.get("user_id", ""))}

        picked = self.bot.storage.with_lock(mutate_pick)
        if not picked.get("ok"):
            return False

        opp_id = str(picked.get("opp_id", ""))
        ok, reason = await self.start_battle_or_fail(interaction, str(user_id), opp_id, "ranked")
        if not ok:
            logger.warning("[RANKED_MATCH_START] failed user=%s opp=%s reason=%s", user_id, opp_id, reason)
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Failed", str(reason)), ephemeral=True)
            return False
        for qid in (str(user_id), str(opp_id)):
            task = self.queue_cpu_tasks.pop(qid, None)
            if task and not task.done():
                task.cancel()
        return True

    async def _queue_timeout(self, interaction: discord.Interaction, user_id: str) -> None:
        await asyncio.sleep(RANKED_QUEUE_TIMEOUT_SECONDS)
        try:
            await self._start_ranked_cpu_battle(interaction, user_id)
        except Exception:
            logger.error("[RANKED_CPU_FALLBACK] failed user=%s\n%s", user_id, traceback.format_exc())
        finally:
            self.queue_cpu_tasks.pop(user_id, None)

    def _cancel_ranked_queue_task(self, user_id: str) -> None:
        task = self.queue_cpu_tasks.pop(str(user_id), None)
        if task and not task.done():
            task.cancel()

    async def _remove_ranked_queue_state(self, user_id: str) -> dict[str, bool]:
        uid = str(user_id)
        removed_json = self.bot.storage.with_lock(lambda data: self._remove_queue_entry(data, uid))
        removed_sqlite = await self.bot.battle_service.remove_queue_user(uid)
        self._cancel_ranked_queue_task(uid)
        return {
            "removed_json": bool(removed_json),
            "removed_sqlite": bool(removed_sqlite),
            "removed": bool(removed_json or removed_sqlite),
        }

    async def _remove_pending_friendly_state(self, target_id: str, *, cancel_task: bool = False) -> dict[str, bool]:
        tid = str(target_id)

        def mutate(data: dict[str, Any]) -> bool:
            pending = self._battle_root(data).get("pending_friendly", {})
            if not isinstance(pending, dict):
                return False
            before = tid in pending
            pending.pop(tid, None)
            return before

        removed_json = self.bot.storage.with_lock(mutate)
        removed_sqlite = await self.bot.battle_service.remove_pending_friendly(tid)
        if cancel_task:
            task = self.friendly_cpu_tasks.pop(tid, None)
            if task and not task.done():
                task.cancel()
        return {
            "removed_json": bool(removed_json),
            "removed_sqlite": bool(removed_sqlite),
            "removed": bool(removed_json or removed_sqlite),
        }

    async def recover_active_battles_after_restart(self) -> dict[str, int]:
        for bucket in (self.turn_tasks, self.battle_stall_tasks, self.queue_cpu_tasks, self.friendly_cpu_tasks):
            for key, task in list(bucket.items()):
                if not task.done():
                    task.cancel()
                bucket.pop(key, None)

        def mutate(data: dict[str, Any]) -> dict[str, int]:
            root = self._battle_root(data)
            self._cleanup_expired(data)
            active = root.get("active", {})
            if not isinstance(active, dict):
                root["active"] = {}
                active = root["active"]

            ended = 0
            cleared = 0
            affected_users: set[str] = set()

            for battle_id, battle in list(active.items()):
                if not isinstance(battle, dict):
                    active.pop(battle_id, None)
                    cleared += 1
                    continue
                players = battle.get("players", {})
                player_ids = {str(pid) for pid in players.keys()} if isinstance(players, dict) else set()
                if not player_ids:
                    active.pop(battle_id, None)
                    cleared += 1
                    continue
                if bool(battle.get("ended", False)):
                    continue
                result = end_battle(data, str(battle_id), "", "", "abandoned")
                if result.get("ok"):
                    ended += 1
                    affected_users.update(player_ids)
                else:
                    active.pop(battle_id, None)
                    cleared += 1
                    affected_users.update(player_ids)

            rebuilt_active_by_user: dict[str, str] = {}
            for battle_id, battle in active.items():
                if not isinstance(battle, dict) or bool(battle.get("ended", False)):
                    continue
                players = battle.get("players", {})
                if not isinstance(players, dict):
                    continue
                for pid in players.keys():
                    rebuilt_active_by_user[str(pid)] = str(battle_id)
            root["active_by_user"] = rebuilt_active_by_user

            return {
                "ended": ended,
                "cleared": cleared,
                "active_by_user": len(rebuilt_active_by_user),
                "affected_users": len(affected_users),
            }

        summary = self.bot.storage.with_lock(mutate)
        refreshed = await self._load_battle_data()
        await self.bot.battle_service.sync_active_by_user_from_data(refreshed)
        if summary["ended"] or summary["cleared"] or summary["affected_users"]:
            logger.warning(
                "[BATTLE_STARTUP_RECOVERY] ended=%s cleared=%s affected_users=%s active_by_user=%s",
                summary["ended"],
                summary["cleared"],
                summary["affected_users"],
                summary["active_by_user"],
            )
        else:
            logger.info("[BATTLE_STARTUP_RECOVERY] no stale active battle state found")
        return summary

    async def _leave_ranked_queue(self, interaction: discord.Interaction, user_id: str, *, message: str = "You've been removed from the ranked queue.") -> bool:
        removed = (await self._remove_ranked_queue_state(user_id))["removed"]
        data = await self._load_battle_data()
        if not removed:
            await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} Not Queued", "You are not currently in the ranked queue."), ephemeral=True)
            return False
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Queue Updated", message), ephemeral=True)
        return True

    async def _start_ranked_cpu_battle(self, interaction: discord.Interaction, user_id: str) -> bool:
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            root = self._battle_root(data)
            queue = root.get("queue", [])
            if not isinstance(queue, list):
                return {"ok": False, "error": "queue_missing"}
            me = next((q for q in queue if isinstance(q, dict) and str(q.get("user_id", "")) == str(user_id)), None)
            if not isinstance(me, dict):
                return {"ok": False, "error": "not_queued"}
            root["queue"] = [q for q in queue if not (isinstance(q, dict) and str(q.get("user_id", "")) == str(user_id))]
            return {"ok": True}

        popped = self.bot.storage.with_lock(mutate)
        if not popped.get("ok"):
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} Not Queued", "You are not currently in the ranked queue."), ephemeral=True)
            return False

        await self.bot.battle_service.remove_queue_user(str(user_id))
        self._cancel_ranked_queue_task(user_id)
        data = await self._load_battle_data()
        cpu = self._make_cpu_participant(data, self._player_trophies(data, user_id))
        ok, reason = await self.start_battle_or_fail(interaction, str(user_id), cpu["cpu_key"], "ranked", cpu_opponent=cpu)
        if not ok:
            logger.warning("[RANKED_CPU_START] failed user=%s reason=%s", user_id, reason)
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Failed", str(reason)), ephemeral=True)
            return False
        return True

    @app_commands.command(name="battle", description="Enter ranked queue.")
    async def battle(self, interaction: discord.Interaction) -> None:
        ok_route, reason, route_channel_id = check_battle_channel_allowed(interaction)
        if not ok_route:
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Channel", f"{reason or 'not_allowed'}: Use <#{route_channel_id}>" if route_channel_id else str(reason or 'not_allowed')), ephemeral=True)
            return
        if not await ensure_registered(interaction, self.bot.storage):
            return

        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            root = self._battle_root(data)
            self._cleanup_expired(data)

            if self._active_battle_id(data, uid):
                return False, "already_battle"
            for q in root.get("queue", []):
                if isinstance(q, dict) and str(q.get("user_id", "")) == uid:
                    return False, "already_queue"
            for inv in root.get("pending_friendly", {}).values():
                if isinstance(inv, dict) and uid in {str(inv.get("challenger_id", "")), str(inv.get("target_id", ""))}:
                    return False, "pending_friendly"

            if not self._snapshot_team(data, uid):
                return False, "no_team"

            joined_at = now_ts()
            root["queue"].append({
                "user_id": uid,
                "joined_at": joined_at,
                "expires_at": joined_at + RANKED_QUEUE_TIMEOUT_SECONDS,
            })
            return True, "ok"

        ok, status = self.bot.storage.with_lock(mutate)
        if ok:
            joined = now_ts()
            await self.bot.battle_service.add_queue_entry(uid, joined, joined + RANKED_QUEUE_TIMEOUT_SECONDS)
        data = await self._load_battle_data()
        if not ok:
            msg = {
                "already_battle": "You're already in an active battle. Use `/forfeit` to exit.",
                "already_queue": "You're already in the ranked queue. Wait for a match.",
                "pending_friendly": "You have a pending friendly invite. Resolve it first.",
                "no_team": "You need at least one fighter in your active squad. Use `/squad` to set one up.",
            }[status]
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Queue Failed", msg), ephemeral=True)
            return

        matched = await self._try_match(interaction, uid)
        if matched:
            self._cancel_ranked_queue_task(uid)
            await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Match Found!", "A ranked opponent was found — battle starting now."), ephemeral=True)
            return

        self._cancel_ranked_queue_task(uid)
        self._track_background_task(
            self.queue_cpu_tasks,
            uid,
            asyncio.create_task(self._queue_timeout(interaction, uid)),
            "ranked_cpu_fallback",
        )
        view = RankedQueueView(self, uid)
        embed = make_embed(
            data,
            f"{e('ranked', data)} Searching for Opponent…",
            f"{e('clock', data)} You've joined the ranked queue.\nIf no match is found within **{RANKED_QUEUE_TIMEOUT_SECONDS} seconds**, you'll face a CPU opponent.",
            fields=[(f"{e('timer', data)} Timeout", f"{RANKED_QUEUE_TIMEOUT_SECONDS} seconds", True), ("Actions", "CPU Battle or Forfeit the queue.", True)],
        )
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True, wait=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            msg = await interaction.original_response()
        if isinstance(msg, discord.Message):
            view.message = msg

    @app_commands.command(name="battle_cancel", description="Cancel ranked queue.")
    async def battle_cancel(self, interaction: discord.Interaction) -> None:
        ok_route, reason, route_channel_id = check_battle_channel_allowed(interaction)
        if not ok_route:
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Channel", f"{reason or 'not_allowed'}: Use <#{route_channel_id}>" if route_channel_id else str(reason or 'not_allowed')), ephemeral=True)
            return
        uid = str(interaction.user.id)
        removed = (await self._remove_ranked_queue_state(uid))["removed"]
        data = await self._load_battle_data()
        if not removed:
            await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} Not Queued", "You are not currently in the ranked queue."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Queue Cancelled", "You've been removed from the ranked queue."), ephemeral=True)

    def _remove_queue_entry(self, data: dict[str, Any], uid: str) -> bool:
        queue = self._battle_root(data).get("queue", [])
        if not isinstance(queue, list):
            return False
        before = len(queue)
        self._battle_root(data)["queue"] = [q for q in queue if not (isinstance(q, dict) and str(q.get("user_id", "")) == uid)]
        return len(self._battle_root(data)["queue"]) != before

    @app_commands.command(name="friendly", description="Send friendly challenge.")
    async def friendly(self, interaction: discord.Interaction, opponent: discord.User) -> None:
        ok_route, reason, route_channel_id = check_battle_channel_allowed(interaction)
        if not ok_route:
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Channel", f"{reason or 'not_allowed'}: Use <#{route_channel_id}>" if route_channel_id else str(reason or 'not_allowed')), ephemeral=True)
            return
        if not await ensure_registered(interaction, self.bot.storage):
            return
        cid = str(interaction.user.id)
        tid = str(opponent.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            root = self._battle_root(data)
            self._cleanup_expired(data)
            if cid == tid:
                return False, "self"
            if not get_player(data, tid):
                return False, "target_unregistered"
            if self._active_battle_id(data, cid) or self._active_battle_id(data, tid):
                return False, "in_battle"
            if not self._snapshot_team(data, cid) or not self._snapshot_team(data, tid):
                return False, "no_team"
            for q in root.get("queue", []):
                if isinstance(q, dict) and str(q.get("user_id", "")) in {cid, tid}:
                    return False, "in_queue"
            root["pending_friendly"][tid] = {"challenger_id": cid, "target_id": tid, "created_at": now_ts(), "expires_at": now_ts() + 60, "message_id": ""}
            return True, "ok"

        ok, status = self.bot.storage.with_lock(mutate)
        if ok:
            await self.bot.battle_service.upsert_pending_friendly(
                tid,
                {"challenger_id": cid, "target_id": tid, "created_at": now_ts(), "expires_at": now_ts() + 60, "message_id": ""},
            )
        data = await self._load_battle_data()
        if not ok:
            msg = {
                "self": "You can't challenge yourself to a friendly match.",
                "target_unregistered": f"{opponent.mention} hasn't registered yet — they need to run `/start` first.",
                "in_battle": "One of you is already in an active battle.",
                "no_team": "Both players need at least one card in their active squad.",
                "in_queue": "One of you is currently in the ranked queue.",
            }[status]
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Challenge Failed", msg), ephemeral=True)
            return

        if interaction.channel:
            view = FriendlyInviteView(self, cid, tid)
            msg = await interaction.channel.send(
                embed=make_embed(
                    data,
                    f"{e('friendly', data)} Friendly Challenge!",
                    f"<@{cid}> has challenged <@{tid}> to a friendly battle!",
                    fields=[
                        (f"{e('timer', data)} Expires In", "60 seconds", True),
                        ("Type", "Friendly — No trophy change", True),
                    ],
                ),
                view=view,
            )
            self.bot.storage.with_lock(lambda d: self._set_pending_message(d, tid, str(msg.id)))
            await self.bot.battle_service.upsert_pending_friendly(
                tid,
                {"challenger_id": cid, "target_id": tid, "created_at": now_ts(), "expires_at": now_ts() + 60, "message_id": str(msg.id)},
            )

        old = self.friendly_cpu_tasks.get(tid)
        if old and not old.done():
            old.cancel()
        self._track_background_task(
            self.friendly_cpu_tasks,
            tid,
            asyncio.create_task(self._friendly_timeout_to_cpu(interaction, cid, tid)),
            "friendly_cpu_fallback",
        )

        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Challenge Sent", f"Your friendly challenge to {opponent.mention} has been sent.\nThey have **60 seconds** to accept."), ephemeral=True)

    def _set_pending_message(self, data: dict[str, Any], tid: str, message_id: str) -> None:
        pending = self._battle_root(data).get("pending_friendly", {}).get(tid)
        if isinstance(pending, dict):
            pending["message_id"] = message_id

    async def _friendly_timeout_to_cpu(self, interaction: discord.Interaction, challenger_id: str, target_id: str) -> None:
        await asyncio.sleep(60)
        challenger = str(challenger_id)
        target = str(target_id)
        try:
            def expire_pending(data: dict[str, Any]) -> dict[str, Any]:
                root = self._battle_root(data)
                pending = root.get("pending_friendly", {}).get(target)
                if not isinstance(pending, dict):
                    return {"ok": False, "error": "missing_pending"}
                if str(pending.get("challenger_id", "")) != challenger:
                    return {"ok": False, "error": "invalid_pending"}
                root.get("pending_friendly", {}).pop(target, None)
                if self._active_battle_id(data, challenger):
                    return {"ok": False, "error": "challenger_active"}
                if not self._snapshot_team(data, challenger):
                    return {"ok": False, "error": "missing_squad"}
                return {"ok": True}

            expired = self.bot.storage.with_lock(expire_pending)
            await self.bot.battle_service.remove_pending_friendly(target)
            if not expired.get("ok"):
                logger.info("[FRIENDLY_TIMEOUT] skipped challenger=%s target=%s reason=%s", challenger, target, expired.get("error", "unknown"))
                return

            data = await self._load_battle_data()
            cpu = self._make_cpu_participant(data, self._player_trophies(data, challenger))
            ok, reason = await self.start_battle_or_fail(interaction, challenger, cpu["cpu_key"], "friendly", cpu_opponent=cpu)
            if not ok:
                logger.warning("[FRIENDLY_TIMEOUT_CPU_START] failed challenger=%s target=%s reason=%s", challenger, target, reason)
                return
            if interaction.channel is not None:
                data = await self._load_battle_data()
                await interaction.channel.send(
                    embed=make_embed(
                        data,
                        f"{e('friendly', data)} Friendly Timed Out",
                        f"<@{target}> did not accept in time, so <@{challenger}> is fighting a CPU opponent.",
                    )
                )
        except Exception:
            logger.exception("[FRIENDLY_TIMEOUT] failed challenger=%s target=%s", challenger, target)
        finally:
            self.friendly_cpu_tasks.pop(target, None)

    async def accept_friendly(self, interaction: discord.Interaction, challenger_id: str, target_id: str) -> None:
        challenger = str(challenger_id)
        acceptor = str(interaction.user.id)
        target = str(target_id)
        now = now_ts()

        if acceptor != target:
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Failed", "invalid_participants"), ephemeral=True)
            return

        def validate_pending(data: dict[str, Any]) -> tuple[bool, str]:
            root = self._battle_root(data)
            pending = root.get("pending_friendly", {}).get(target)
            if not isinstance(pending, dict):
                return False, "missing_data"
            if str(pending.get("challenger_id", "")) != challenger:
                return False, "invalid_participants"
            if str(pending.get("target_id", "")) != target:
                return False, "invalid_participants"
            if int(pending.get("expires_at", 0)) < now:
                root.get("pending_friendly", {}).pop(target, None)
                return False, "expired"
            if challenger == target:
                return False, "invalid_participants"
            if self._active_battle_id(data, challenger) or self._active_battle_id(data, target):
                return False, "already_active"
            if not self._snapshot_team(data, challenger) or not self._snapshot_team(data, target):
                return False, "missing_squad"
            return True, "ok"

        valid, reason = self.bot.storage.with_lock(validate_pending)
        t = self.friendly_cpu_tasks.pop(target, None)
        if t and not t.done():
            t.cancel()
        if not valid:
            logger.warning("[FRIENDLY_ACCEPT] validation failed challenger=%s target=%s reason=%s", challenger, target, reason)
            if reason in {"expired", "missing_data", "invalid_participants"}:
                await self.bot.battle_service.remove_pending_friendly(target)
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Failed", str(reason)), ephemeral=True)
            return

        ok, reason = await self.start_battle_or_fail(interaction, challenger, target, "friendly", clear_pending_target_id=target)
        data = await self._load_battle_data()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Failed", str(reason)), ephemeral=True)
            return

        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Challenge Accepted!", "The friendly battle has started — good luck!"), ephemeral=True)

    @app_commands.command(name="friendly_cancel", description="Cancel outgoing friendly challenge.")
    async def friendly_cancel(self, interaction: discord.Interaction) -> None:
        ok_route, reason, route_channel_id = check_battle_channel_allowed(interaction)
        if not ok_route:
            data = await self._load_battle_data()
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Battle Channel", f"{reason or 'not_allowed'}: Use <#{route_channel_id}>" if route_channel_id else str(reason or 'not_allowed')), ephemeral=True)
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> bool:
            pending = self._battle_root(data).get("pending_friendly", {})
            if not isinstance(pending, dict):
                return False
            removed = False
            for key, inv in list(pending.items()):
                if isinstance(inv, dict) and str(inv.get("challenger_id", "")) == uid:
                    pending.pop(key, None)
                    removed = True
            return removed

        removed = self.bot.storage.with_lock(mutate)
        if removed:
            await self.bot.battle_service.clear_outgoing_pending(uid)
        for tid, task in list(self.friendly_cpu_tasks.items()):
            if tid == uid and task and not task.done():
                task.cancel()
                self.friendly_cpu_tasks.pop(tid, None)
        data = await self._load_battle_data()
        if not removed:
            await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} No Active Challenge", "You don't have any outgoing friendly challenges to cancel."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Challenge Cancelled", "Your outgoing friendly challenge has been cancelled."), ephemeral=True)

    @app_commands.command(name="o_battle_unstuck", description="Owner: clear stuck battle/pending state for a user.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_battle_unstuck(self, interaction: discord.Interaction, target: discord.User | None = None) -> None:
        data = await self._load_battle_data()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "You are not allowed to use this command."), ephemeral=True)
            return

        uid = str((target.id if target else interaction.user.id))

        def mutate(d: dict[str, Any]) -> tuple[int, int]:
            users = {uid}
            root = self._battle_root(d)
            active = root.get("active", {})
            if isinstance(active, dict):
                for _bid, b in list(active.items()):
                    if not isinstance(b, dict):
                        continue
                    players = b.get("players", {})
                    if isinstance(players, dict) and uid in {str(x) for x in players.keys()}:
                        users.update({str(x) for x in players.keys()})
            removed_active = self._rollback_battle_for_users(d, users)

            pending = root.get("pending_friendly", {})
            removed_pending = 0
            if isinstance(pending, dict):
                for key, inv in list(pending.items()):
                    if not isinstance(inv, dict):
                        continue
                    if uid in {str(inv.get("challenger_id", "")), str(inv.get("target_id", ""))}:
                        pending.pop(key, None)
                        removed_pending += 1

            queue = root.get("queue", [])
            if isinstance(queue, list):
                root["queue"] = [q for q in queue if not (isinstance(q, dict) and str(q.get("user_id", "")) in users)]
            return removed_active, removed_pending

        removed_active, removed_pending = self.bot.storage.with_lock(mutate)
        if removed_active or removed_pending:
            await self.bot.battle_service.clear_outgoing_pending(uid)
            await self.bot.battle_service.remove_queue_user(uid)
            await self.bot.battle_service.sync_active_by_user_from_data(self.bot.storage.load())
        logger.warning("[BATTLE_UNSTUCK] user=%s removed_active=%s removed_pending=%s", uid, removed_active, removed_pending)
        data = await self._load_battle_data()
        await smart_reply(
            interaction,
            embed=make_embed(
                data,
                f"{e('ok', data)} Battle State Cleared",
                f"Stuck state has been resolved for <@{uid}>.",
                fields=[
                    ("Active Battles Removed", str(removed_active), True),
                    ("Pending Invites Removed", str(removed_pending), True),
                ],
            ),
            ephemeral=True,
        )

    async def forfeit_internal(self, interaction: discord.Interaction, user_id: str) -> None:
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            bid = self._active_battle_id(data, user_id)
            if not bid:
                return {"ok": False}
            battle = self._battle_root(data).get("active", {}).get(bid)
            if not isinstance(battle, dict):
                return {"ok": False}
            winner = ""
            for pid in (battle.get("players", {}) or {}).keys():
                if pid != user_id:
                    winner = pid
                    break
            result = end_battle(data, bid, winner, user_id, "forfeit")
            json_safe_battle_state(battle)
            result["battle_id"] = bid
            return result

        result = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not result.get("ok"):
            if interaction.response.is_done():
                await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} No Active Battle", "You don't have an active battle to forfeit."), ephemeral=True)
            else:
                await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} No Active Battle", "You don't have an active battle to forfeit."), ephemeral=True)
            return

        # Sync SQLite so user can battle again immediately
        await self.bot.battle_service.sync_active_by_user_from_data(data)

        await self._refresh_battle_message(str(result.get("battle_id", "")))
        if interaction.response.is_done():
            await smart_reply(interaction, embed=make_embed(data, f"{e('forfeit', data)} Battle Forfeited", "You've forfeited the battle. Better luck next time!"), ephemeral=True)
        else:
            await smart_reply(interaction, embed=make_embed(data, f"{e('forfeit', data)} Battle Forfeited", "You've forfeited the battle. Better luck next time!"), ephemeral=True)

    @app_commands.command(name="forfeit", description="Forfeit your active battle.")
    async def forfeit(self, interaction: discord.Interaction) -> None:
        await self.forfeit_internal(interaction, str(interaction.user.id))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BattleCog(bot))
