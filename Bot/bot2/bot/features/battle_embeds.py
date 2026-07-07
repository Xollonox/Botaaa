"""Embed builders for battle state.

Extracted from BattleCog. `build_embed_view` takes the cog as first argument
to reuse per-battle helpers (`_current_uid`, `_fighter_attack_rows`,
`_switch_options`, `forfeit_internal`) — everything else is pure formatting.
"""

from __future__ import annotations

import logging
from typing import Any

import discord

from bot.utils.battle_engine_pdf import normalize_attack_type
from bot.utils.cards_logic import find_catalog_card
from bot.utils.squad_logic import get_player
from bot.utils.ui import e, make_embed

from bot.features.battle_helpers import card_image_url, option_emoji
from bot.features.battle_views import TurnView

logger = logging.getLogger(__name__)


def build_battle_stats_embed(battle_state: dict, winner_name: str) -> discord.Embed:
    """Build a detailed post-battle results embed."""
    embed = discord.Embed(title="\u2694\uFE0F Battle Results", color=0xFFD700)

    # ── Parse players, logs, moves ──────────────────────────────────
    players: dict[str, Any] = battle_state.get("players", {}) if isinstance(battle_state.get("players"), dict) else {}
    pid_list = list(players.keys())

    damage_by_pid: dict[str, int] = {pid: 0 for pid in pid_list}
    move_counts: dict[str, dict[str, int]] = {
        pid: {"normal": 0, "special": 0, "ultimate": 0, "unique_skill": 0, "unique_path": 0, "parry": 0, "dodge": 0, "block": 0, "revert": 0, "tank": 0}
        for pid in pid_list
    }
    total_moves_per_pid: dict[str, int] = {pid: 0 for pid in pid_list}
    logs = battle_state.get("log", []) if isinstance(battle_state.get("log"), list) else []
    for entry in logs:
        if not isinstance(entry, str):
            continue
        parts = entry.split(":", 2)
        if len(parts) == 3 and parts[0] and parts[1]:
            pid, move_raw, dmg_raw = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if pid not in damage_by_pid:
                continue
            total_moves_per_pid[pid] += 1
            try:
                dmg = int(dmg_raw)
                if dmg > 0:
                    damage_by_pid[pid] += dmg
            except (ValueError, TypeError):
                pass
            norm = normalize_attack_type(move_raw)
            mc = move_counts[pid]
            if norm in mc:
                mc[norm] += 1
            else:
                mc["normal"] += 1

    # ── Header: outcome + basic info ─────────────────────────────────
    reason = str(battle_state.get("reason", ""))
    outcome_map = {
        "all_fainted":        "\u2620\uFE0F K.O.",
        "no_active_fighter":  "\u2620\uFE0F K.O.",
        "forfeit":            "🏳\uFE0F Forfeit",
        "timeout_abandoned":  "\u23F3 Timeout",
        "abandoned":          "🤝 No Contest",
        "no_contest":         "🤝 No Contest",
        "draw":               "🤝 Draw",
    }
    outcome_label = outcome_map.get(reason, reason.replace("_", " ").title() if reason else "Unknown")
    rounds = int(battle_state.get("round", 1))
    created_at = int(battle_state.get("created_at", 0))
    last_ts = int(battle_state.get("turn_started_at", 0))
    duration_str = ""
    if created_at and last_ts and last_ts > created_at:
        secs = last_ts - created_at
        duration_str = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"
    battle_type = str(battle_state.get("type", "ranked")).upper()

    header = f"{battle_type} \u2022 {outcome_label} \u2022 Round {rounds}"
    if duration_str:
        header += f" \u2022 {duration_str}"
    embed.description = header
    embed.add_field(name="🏆 Winner", value=winner_name or "\u2014", inline=True)

    # ── Side display helper ──────────────────────────────────────────
    def _player_label(pid: str) -> str:
        pstate = players.get(pid, {}) if isinstance(players.get(pid), dict) else {}
        if isinstance(pstate, dict) and bool(pstate.get("is_cpu", False)):
            cpu_meta = pstate.get("cpu_meta", {}) or {}
            return str(cpu_meta.get("display_name", "🤖 CPU")) if isinstance(cpu_meta, dict) else "🤖 CPU"
        return f"<@{pid}>"

    # ── Squad breakdown per side (inline, side by side) ──────────────
    for pid in pid_list:
        pstate = players.get(pid, {}) if isinstance(players.get(pid), dict) else {}
        if not isinstance(pstate, dict):
            continue
        team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []
        names = pstate.get("fighter_names", {}) if isinstance(pstate.get("fighter_names"), dict) else {}
        hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
        hp_max = pstate.get("hp_max", {}) if isinstance(pstate.get("hp_max"), dict) else {}

        fighter_lines: list[str] = []
        for uid in team:
            uid_s = str(uid)
            fighter_name = str(names.get(uid_s, uid_s[:8]))
            cur_hp = int(hp.get(uid_s, 0))
            mx_hp = int(hp_max.get(uid_s, 1))
            alive = cur_hp > 0
            bar = _hp_bar(cur_hp, mx_hp, 8)
            fighter_lines.append(
                f"{'✅' if alive else '\u2620\uFE0F'} {fighter_name}"
                f"\n{bar} {cur_hp}/{mx_hp} HP"
            )

        dmg = damage_by_pid.get(pid, 0)
        total_moves = total_moves_per_pid.get(pid, 0)
        summary_line = f"🗡 {dmg} dmg \u2022 🎯 {total_moves} moves"
        alive_count = sum(1 for uid in team if int(hp.get(str(uid), 0)) > 0)
        if alive_count > 0:
            summary_line += f" \u2022 ✅ {alive_count} alive"
        fighter_lines.append(summary_line)
        embed.add_field(name=_player_label(pid), value="\n".join(fighter_lines), inline=True)

    # ── All Moves Used ───────────────────────────────────────────────
    move_emoji_map = {
        "normal": "🔷", "special": "🔶", "ultimate": "🔥",
        "unique_skill": "\u2728", "unique_path": "🌀",
        "parry": "🛡\uFE0F", "dodge": "\u26A1", "block": "🔑", "revert": "🔄", "tank": "🛡",
    }
    move_labels = {
        "normal": "Normal", "special": "Special", "ultimate": "Ultimate",
        "unique_skill": "Skill", "unique_path": "Path",
        "parry": "Parry", "dodge": "Dodge", "block": "Block", "revert": "Revert", "tank": "Tank",
    }

    # Show ALL move types used by BOTH parties in one field
    all_moves_lines: list[str] = []
    for pid in pid_list:
        mc = move_counts.get(pid, {})
        player_moves = [(cat, count) for cat, count in mc.items() if count > 0]
        if player_moves:
            all_moves_lines.append(f"**{_player_label(pid)}**")
            for cat, count in player_moves:
                emoji = move_emoji_map.get(cat, "\u25B6")
                label = move_labels.get(cat, cat.title())
                all_moves_lines.append(f"{emoji} {label} \u00d7{count}")
        else:
            all_moves_lines.append(f"**{_player_label(pid)}** \u2014")
    if all_moves_lines:
        embed.add_field(name="🎯 Moves Used", value="\n".join(all_moves_lines), inline=False)

    # ── Damage Comparison ────────────────────────────────────────────
    if len(pid_list) == 2:
        a_pid, b_pid = pid_list[0], pid_list[1]
        a_dmg = damage_by_pid.get(a_pid, 0)
        b_dmg = damage_by_pid.get(b_pid, 0)
        total_dmg = a_dmg + b_dmg
        if total_dmg > 0:
            a_pct = a_dmg / total_dmg * 100
            b_pct = b_dmg / total_dmg * 100
            bar_a = _hp_bar(a_dmg, total_dmg, 10)
            bar_b = _hp_bar(b_dmg, total_dmg, 10)
            comparison = (
                f"{_player_label(a_pid)}\n{bar_a} {a_dmg:,} ({a_pct:.0f}%)\n\n"
                f"{_player_label(b_pid)}\n{bar_b} {b_dmg:,} ({b_pct:.0f}%)"
            )
            embed.add_field(name="🗡\uFE0F Damage Comparison", value=comparison, inline=False)

    # ── Rewards ──────────────────────────────────────────────────────
    trophy_changes = battle_state.get("pvp_trophy_changes", {})
    cpu_trophy_change = battle_state.get("cpu_trophy_change")
    coin_reward = battle_state.get("coin_reward")
    reward_lines: list[str] = []
    if trophy_changes and isinstance(trophy_changes, dict):
        for pid, delta in trophy_changes.items():
            sign = "+" if delta >= 0 else ""
            reward_lines.append(f"<@{pid}>: {sign}{delta} 🏆")
    elif cpu_trophy_change is not None:
        sign = "+" if cpu_trophy_change >= 0 else ""
        reward_lines.append(f"{_player_label(pid_list[0])}: {sign}{cpu_trophy_change} 🏆")
    if coin_reward:
        reward_lines.append(f"💰 +{coin_reward:,} coins")
    for key, label in (("winner_milestone_packs", "🎁 Winner Pack"),
                       ("loser_milestone_packs", "🎁 Loser Pack")):
        if key in battle_state and battle_state[key]:
            packs = battle_state[key]
            reward_lines.append(f"{label}: {', '.join(str(p).replace('_', ' ').title() for p in packs)}")
    for pid in pid_list:
        pk = f"{pid}_milestone_packs"
        if pk in battle_state and isinstance(battle_state.get(pk), list) and battle_state[pk]:
            reward_lines.append(f"🎁 {_player_label(pid)} milestone: {', '.join(str(p).replace('_', ' ').title() for p in battle_state[pk])}")
    if reward_lines:
        embed.add_field(name="💰 Rewards", value="\n".join(reward_lines), inline=False)

    embed.set_footer(text="Battle Results \u2022 Lookism HXCC")
    return embed


def _hp_bar(cur: int, max_hp: int, slots: int = 10) -> str:
    """Return a compact HP bar string."""
    if max_hp <= 0:
        return "\u2591" * slots
    pct = max(0, min(100, int(cur / max_hp * 100)))
    filled = round(pct / 100 * slots)
    return "\u2588" * filled + "\u2591" * (slots - filled)


def build_embed_view(
    cog: Any,
    data: dict[str, Any],
    battle_id: str,
    display_hp_override: dict[str, int] | None = None,
) -> tuple[discord.Embed | None, discord.Embed | None, discord.Embed | None, TurnView | None]:
    try:
        battle = cog._lookup_battle(data, battle_id)
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
            cdef = find_catalog_card(cards, card_name) if isinstance(cards, dict) else None
            if not isinstance(cdef, dict):
                cdef = {}
            return card_name, cdef

        def hp_bar(pct: int, slots: int = 12) -> str:
            pct = max(0, min(100, pct))
            filled = round(pct / 100 * slots)
            return "█" * filled + "░" * (slots - filled)

        def side_panel(pid: str, pstate: dict[str, Any], label: str) -> str:
            uid = cog._current_uid(pstate)
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
                f"HP:  {hp_bar(pct)}  {cur_hp}/{max_hp} ({pct}%)",
            ]
            stamina_map = pstate.get("stamina", {}) if isinstance(pstate.get("stamina"), dict) else {}
            cur_sta = max(0, int(stamina_map.get(uid, 100)))
            sta_pct = int(round((cur_sta / 100) * 100))
            exhausted = cur_sta <= 0
            sta_label = " [EXHAUSTED]" if exhausted else ""
            lines.append(f"STA: {hp_bar(sta_pct)}  {cur_sta}/100{sta_label}")
            lines.append(f"STR {s('strength')} | SPD {s('speed')} | END {s('endurance')} | TEC {s('technique')} | IQ {s('iq')} | BIQ {s('biq')}")
            return "\n".join(lines)

        def squad_block(label: str, pstate: dict[str, Any]) -> str:
            team = pstate.get("team_uids", []) if isinstance(pstate.get("team_uids"), list) else []
            hp = pstate.get("hp", {}) if isinstance(pstate.get("hp"), dict) else {}
            hp_max = pstate.get("hp_max", {}) if isinstance(pstate.get("hp_max"), dict) else {}
            cur_uid = cog._current_uid(pstate)
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
            user = cog.bot.get_user(int(pid)) if str(pid).isdigit() else None
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

        turn_label = "CPU" if bool((turn_state or {}).get("is_cpu", False)) else f"<@{turn_user}>"
        mode_label = str(battle.get("type", "ranked")).upper()

        # ── Thumbnails for each side's active fighter ────────
        a_uid = cog._current_uid(a) if isinstance(a, dict) else ""
        a_img = card_image_url(fighter_bundle(a_uid, a)[1]) if a_uid else None
        b_uid = cog._current_uid(b) if isinstance(b, dict) else ""
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

        header = f"{mode_label} DUEL"
        embed_a = make_embed(None, header, desc_a, color=0x2b2d31, image_url=a_img)
        embed_b = make_embed(None, "", desc_b, color=0x2b2d31, image_url=b_img)
        log_display = log_text[:1024] if log_text else "—"
        turn_line = f"**Turn:** {turn_label}  •  **Round:** {round_no}\n\n"
        embed_c = make_embed(None, f"{e('list', data)} Battle Log", turn_line + log_display, color=0x2b2d31)

    except Exception:
        logger.exception("[BATTLE_EMBED_ERROR] battle_id=%s", battle_id)
        # Return a basic view with forfeit button so user can always escape
        fallback_view = discord.ui.View(timeout=300)
        fallback_btn = discord.ui.Button(label="🏳️ Forfeit", style=discord.ButtonStyle.danger, row=0)
        async def fb_cb(i: discord.Interaction):
            await cog.forfeit_internal(i, str(i.user.id))
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
            ended_log = f"**Turn:** {turn_label}  •  **Round:** {round_no}  •  *Ended*\n\n" if turn_label else ""
            embed_c_log = make_embed(None, f"{e('list', data)} Battle Log — Ended", ended_log + (log_text[:1024] if log_text else "—"), color=0x2b2d31)
            return embed_a, embed_b, embed_c_log, None

        if end_reason == "draw":
            result_lines = [
                "🤝 Draw",
                "Both sides were knocked out at the same time.",
            ]
            embed_a.description = "─" * 32 + "\n" + "\n".join(result_lines) + "\n" + "─" * 32 + "\n\n" + (embed_a.description or "")
            ended_log = f"**Turn:** {turn_label}  •  **Round:** {round_no}  •  *Ended*\n\n" if turn_label else ""
            embed_c_log = make_embed(None, "Battle Log — Ended", ended_log + (log_text[:1024] if log_text else "—"), color=0x2b2d31)
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
        ended_log = f"**Turn:** {turn_label}  •  **Round:** {round_no}  •  *Ended*\n\n" if turn_label else ""
        embed_c_log = make_embed(None, "Battle Log \u2014 Ended", ended_log + (log_text[:1024] if log_text else "\u2014"), color=0x2b2d31)
        return embed_a, embed_b, embed_c_log, None

    offensive, defensive = cog._fighter_attack_rows(data, battle_id, turn_user)
    switch_opts = cog._switch_options(data, battle_id, turn_user)

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
    view = TurnView(cog, battle_id, turn_user, attack_opts, defense_opts, sw_opts, enemy_id=b_id if turn_user == a_id else a_id)
    if isinstance(turn_state, dict) and bool(turn_state.get("is_cpu", False)):
        for item in view.children:
            item.disabled = True
    return embed_a, embed_b, embed_c, view
