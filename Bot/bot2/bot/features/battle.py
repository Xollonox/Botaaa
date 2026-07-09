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
from bot.utils.cards_logic import find_catalog_card
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
    IDLE_SKIP_LIMIT_VS_CPU,
)

from bot.features.battle_views import (
    TurnView,
    FriendlyInviteView,
    RankedQueueView,
    ForfeitButton,
)

from bot.features.battle_cpu import (
    _cpu_pick_move,
    choose_cpu_move as _choose_cpu_move_impl,
)
from bot.features.battle_embeds import (
    build_battle_stats_embed,
    build_embed_view as _build_embed_view_impl,
)

logger = logging.getLogger(__name__)
OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)
RANKED_QUEUE_TIMEOUT_SECONDS = 60



class BattleCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.turn_tasks: dict[str, asyncio.Task[Any]] = {}
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
        for bucket in (self.turn_tasks, self.timer_tasks):
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
                    cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
                    card_def = find_catalog_card(cards, card_name) if isinstance(cards, dict) else None
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
                    cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
                    card_def = find_catalog_card(cards, card_name) if isinstance(cards, dict) else None
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

        # Track voluntary swap count (used for both sides)
        swaps_used = int(me.get("swaps_used", 0))
        if swaps_used >= 2:
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
            maybe = find_catalog_card(cards, card_name) if card_name else None
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
            maybe = find_catalog_card(cards, card_name) if card_name else None
            card_def = maybe if isinstance(maybe, dict) else {}

        moves = normalize_card_moves(card_def)
        uses_map = pstate.get("attack_uses", {}).get(uid, {}) if isinstance(pstate.get("attack_uses", {}), dict) else {}
        stamina_map = pstate.get("stamina", {}) if isinstance(pstate.get("stamina"), dict) else {}
        cur_stamina = int(stamina_map.get(uid, 100))
        is_exhausted = cur_stamina <= 0
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
                if left != 0 and not (is_exhausted and norm_type != "normal"):
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

        # Both sides get up to 2 voluntary swaps per battle
        if int(pstate.get("swaps_used", 0)) >= 2:
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
            cdef = find_catalog_card(cards, name) if isinstance(cards, dict) else None
            if not isinstance(cdef, dict):
                cdef = {}
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
        return _build_embed_view_impl(self, data, battle_id, display_hp_override)

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
        card_def = find_catalog_card(cards, card_name) if isinstance(cards, dict) else None
        if not isinstance(card_def, dict):
            card_def = {}
        return card_image_url(card_def), card_name or None

    async def _send_stats_once(self, battle_id: str, battle: dict, channel: Any) -> bool:
        """Atomically mark stats_sent and send the embed. Returns True if sent."""
        def _try_mark(data: dict) -> bool:
            for entry in self._battle_root(data).get("recently_ended", []):
                if isinstance(entry, dict) and str(entry.get("battle_id", "")) == battle_id:
                    if entry.get("stats_sent"):
                        return False
                    entry["stats_sent"] = True
                    return True
            return False

        first = self.bot.storage.with_lock(_try_mark)
        if first:
            await self._send_battle_stats_embed(channel, battle)
        return first

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
        if bool(battle.get("ended", False)):
            if await self._send_stats_once(battle_id, battle, channel):
                logger.info("[BATTLE_STATS] sent stats embed for ended battle_id=%s", battle_id)

    def _schedule_timeout(self, battle_id: str) -> None:
        pass

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
        return _choose_cpu_move_impl(self, data, battle_id, cpu_id, enemy_id)

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
            # Send the battle stats summary if not already sent (atomic check)
            if isinstance(battle, dict):
                channel = getattr(interaction, "channel", None)
                if channel is None:
                    try:
                        channel = await interaction.original_response()
                        channel = getattr(channel, "channel", None)
                    except Exception:
                        channel = None
                if channel is not None:
                    if await self._send_stats_once(battle_id, battle, channel):
                        logger.info("[BATTLE_STATS] sent stats embed for ended battle_id=%s", battle_id)
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

    async def _queue_loop(self, interaction: discord.Interaction, user_id: str) -> None:
        """Periodically re-check for a match every 10s. Falls back to CPU after timeout."""
        remaining = RANKED_QUEUE_TIMEOUT_SECONDS
        while remaining > 0:
            await asyncio.sleep(min(10, remaining))
            remaining -= 10

            # Try to find a match
            try:
                matched = await self._try_match(interaction, user_id)
                if matched:
                    # Battle started — task is done
                    return
            except Exception:
                logger.exception("[QUEUE_LOOP_MATCH] failed user=%s", user_id)

            # Check if user is still in queue (could have been removed by forfeit)
            def still_queued(data: dict[str, Any]) -> bool:
                queue = self._battle_root(data).get("queue", [])
                return any(
                    isinstance(q, dict) and str(q.get("user_id", "")) == str(user_id)
                    for q in queue
                )
            if not self.bot.storage.with_lock(still_queued):
                logger.info("[QUEUE_LOOP] user=%s no longer in queue, ending loop", user_id)
                return

        # Timeout reached — start CPU battle
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
        for bucket in (self.turn_tasks, self.queue_cpu_tasks, self.friendly_cpu_tasks):
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
                # Keep active battles alive — do not end them on restart
                if bool(battle.get("ended", False)):
                    continue

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
            }

        summary = self.bot.storage.with_lock(mutate)
        refreshed = await self._load_battle_data()
        await self.bot.battle_service.sync_active_by_user_from_data(refreshed)

        # Rebuild fresh views for every active battle
        data = self.bot.storage.load()
        active = self._battle_root(data).get("active", {}) if isinstance(self._battle_root(data).get("active"), dict) else {}
        refreshed_count = 0
        for battle_id, battle in list(active.items()):
            if not isinstance(battle, dict) or bool(battle.get("ended", False)):
                continue
            channel_id = int(str(battle.get("message_channel_id", "0")) or 0)
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            embed_a, embed_b, embed_c, view = self._build_embed_view(data, battle_id)
            if view is not None:
                style_view(view, data)
            msg = await channel.send(
                embeds=[e for e in (embed_a, embed_b, embed_c) if e is not None],
                view=view,
            )
            if view is not None and hasattr(view, "message"):
                view.message = msg

            # Persist new message IDs
            def persist(bid: str = battle_id, cid: int = channel.id, mid: int = msg.id) -> None:
                def _save(d: dict[str, Any]) -> None:
                    b = self._battle_root(d).get("active", {}).get(bid)
                    if isinstance(b, dict):
                        b["message_channel_id"] = str(cid)
                        b["message_id"] = str(mid)
                return _save

            self.bot.storage.with_lock(persist(battle_id, channel.id, msg.id))
            refreshed_count += 1

        if summary["ended"] or summary["cleared"] or refreshed_count:
            logger.info(
                "[BATTLE_RECOVER] ended=%s cleared=%s refreshed=%s active_by_user=%s",
                summary["ended"], summary["cleared"], refreshed_count, summary["active_by_user"],
            )
        else:
            logger.info("[BATTLE_STARTUP_RECOVERY] no stale active battle state found")
        return {**summary, "refreshed": refreshed_count}

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

        await interaction.response.defer(ephemeral=True, thinking=True)
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
            asyncio.create_task(self._queue_loop(interaction, uid)),
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
            try:
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
                view.message = msg
                self.bot.storage.with_lock(lambda d: self._set_pending_message(d, tid, str(msg.id)))
                await self.bot.battle_service.upsert_pending_friendly(
                    tid,
                    {"challenger_id": cid, "target_id": tid, "created_at": now_ts(), "expires_at": now_ts() + 60, "message_id": str(msg.id)},
                )
            except discord.Forbidden:
                # Clean up the pending challenge that was already created
                self.bot.storage.with_lock(lambda d: self._battle_root(d).get("pending_friendly", {}).pop(tid, None))
                await self.bot.battle_service.remove_pending_friendly(tid)
                await smart_reply(
                    interaction,
                    embed=make_embed(data, f"{e('warning', data)} Cannot Send", f"I don't have permission to send messages in this channel."),
                    ephemeral=True,
                )
                return

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
                    return {"ok": False, "error": "missing_pending", "message_id": ""}
                if str(pending.get("challenger_id", "")) != challenger:
                    return {"ok": False, "error": "invalid_pending", "message_id": ""}
                msg_id = str(pending.get("message_id", ""))
                root.get("pending_friendly", {}).pop(target, None)
                if self._active_battle_id(data, challenger):
                    return {"ok": False, "error": "challenger_active", "message_id": msg_id}
                if not self._snapshot_team(data, challenger):
                    return {"ok": False, "error": "missing_squad", "message_id": msg_id}
                return {"ok": True, "message_id": msg_id}

            expired = self.bot.storage.with_lock(expire_pending)
            await self.bot.battle_service.remove_pending_friendly(target)
            msg_id = str(expired.get("message_id", ""))
            if not expired.get("ok"):
                logger.info("[FRIENDLY_TIMEOUT] skipped challenger=%s target=%s reason=%s", challenger, target, expired.get("error", "unknown"))
                return

            data = await self._load_battle_data()
            cpu = self._make_cpu_participant(data, self._player_trophies(data, challenger))
            ok, reason = await self.start_battle_or_fail(interaction, challenger, cpu["cpu_key"], "friendly", cpu_opponent=cpu)
            if not ok:
                logger.warning("[FRIENDLY_TIMEOUT_CPU_START] failed challenger=%s target=%s reason=%s", challenger, target, reason)
                return

            # Update the original challenge message to show expired (view.on_timeout should also handle this)
            if msg_id and msg_id.isdigit() and interaction.channel:
                try:
                    old_msg = await interaction.channel.fetch_message(int(msg_id))
                    data = await self._load_battle_data()
                    await old_msg.edit(
                        embed=make_embed(
                            data,
                            f"{e('warning', data)} Challenge Expired",
                            f"<@{target}> did not accept in time, so <@{challenger}> is now fighting a CPU opponent.",
                        ),
                        view=None,
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

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
