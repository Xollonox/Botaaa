"""Tournament system — 24hr XP race between participants."""
from __future__ import annotations
import asyncio
import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed
from bot.utils.xp_logic import make_bar
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.config import OWNER_GUILD_ID

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)
PRIZE_SPLIT = [0.40, 0.20, 0.12, 0.08, 0.05, 0.05, 0.025, 0.025, 0.025, 0.025]

def _e(desc: str, color: int = 0x2B2D31) -> discord.Embed:
    return make_embed(None, "LOOKISM HXCC • TOURNAMENT", desc, color=color, footer="Tournament System")

def _ok(d: str)  -> discord.Embed: return _e(d, 0x2ECC71)
def _err(d: str) -> discord.Embed: return _e(d, 0xE74C3C)
def _inf(d: str) -> discord.Embed: return _e(d, 0xE11D48)

def _t_root(data: dict[str, Any]) -> dict[str, Any]:
    t = data.setdefault("tournament", {})
    t.setdefault("active",      False)
    t.setdefault("name",        "")
    t.setdefault("entry_fee",   0)
    t.setdefault("max_players", 16)
    t.setdefault("prize_pool",  0)
    t.setdefault("start_time",  0)
    t.setdefault("end_time",    0)
    t.setdefault("participants",{})  # uid → {name, xp_earned, paid}
    return t

def _time_left(end_time: int) -> str:
    remaining = max(0, end_time - now_ts())
    h, rem = divmod(remaining, 3600)
    m      = rem // 60
    return f"{h}h {m}m"

def _get_leaderboard(t: dict) -> list[tuple[str, str, int]]:
    participants = t.get("participants", {}) or {}
    lb = [(uid, p.get("name", uid), int(p.get("xp_earned", 0)))
          for uid, p in participants.items() if isinstance(p, dict)]
    lb.sort(key=lambda x: x[2], reverse=True)
    return lb


class TournamentCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._end_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        data = self.bot.storage.load()
        tournament = _t_root(data)
        if tournament.get("active"):
            self._schedule_end(max(0, int(tournament.get("end_time", 0)) - now_ts()))

    def cog_unload(self) -> None:
        if self._end_task and not self._end_task.done():
            self._end_task.cancel()

    def _schedule_end(self, delay_seconds: int) -> None:
        if self._end_task and not self._end_task.done():
            self._end_task.cancel()

        async def auto_end() -> None:
            await asyncio.sleep(max(0, int(delay_seconds)))
            await self._end_tournament()

        self._end_task = asyncio.create_task(auto_end())

    # ── /tournament ───────────────────────────────────────────────

    @app_commands.command(name="tournament", description="View active tournament leaderboard.")
    async def tournament(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        t    = _t_root(data)
        uid  = str(interaction.user.id)

        if not t.get("active"):
            await smart_reply(interaction, embed=_inf("╭─ ⚔️ No Active Tournament\n│ No tournament is running right now.\n╰────────────────"))
            return

        lb     = _get_leaderboard(t)
        medals = [e("winner",data), "🥈", "🥉"] + [f" {i}." for i in range(4, 11)]
        pool   = int(t.get("prize_pool", 0))
        SEP    = "━" * 32

        prize_lines = []
        for i, (uid2, name, xp) in enumerate(lb[:10]):
            if i >= len(PRIZE_SPLIT): break
            coins = int(pool * PRIZE_SPLIT[i])
            prize_lines.append(f"│  {medals[i]}  {name:<18} {xp:,} XP   💰 {coins:,}")

        my_entry   = t.get("participants", {}).get(uid)
        my_xp      = int(my_entry.get("xp_earned", 0)) if isinstance(my_entry, dict) else 0
        my_rank    = next((i+1 for i, (u,_,_) in enumerate(lb) if u == uid), 0)
        in_tourney = uid in (t.get("participants", {}) or {})

        body = (
            f"{SEP}\n  ⚔️  {t.get('name','Tournament').upper()}\n{SEP}\n\n"
            f"╭─ 📋 Tournament Info\n"
            f"│  ⏳ Time Left:    {_time_left(int(t.get('end_time',0)))}\n"
            f"│  💰 Entry Fee:   {int(t.get('entry_fee',0)):,} coins\n"
            f"│  🏆 Prize Pool:  {pool:,} coins\n"
            f"│  👥 Players:     {len(lb)} / {int(t.get('max_players',16))}\n"
            f"╰────────────────────────────────\n\n"
            f"╭─ 🏆 Leaderboard\n"
            + ("\n".join(prize_lines) if prize_lines else "│  No participants yet.")
            + "\n╰────────────────────────────────"
            + (
                f"\n\n╭─ 📊 Your Standing\n"
                f"│  Rank #{my_rank}  •  {my_xp:,} XP earned\n"
                "╰────────────────────────────────"
                if in_tourney else ""
            )
        )

        view = discord.ui.View(timeout=60)
        if not in_tourney:
            join_btn = discord.ui.Button(label=f"⚔️ Join — {int(t.get('entry_fee',0)):,} coins", style=discord.ButtonStyle.success, row=0)
            async def join_cb(i: discord.Interaction) -> None:
                if str(i.user.id) != uid:
                    await i.response.send_message("Not your panel.", ephemeral=True)
                    return
                await self._join_tournament(i)
            join_btn.callback = join_cb
            view.add_item(join_btn)
        else:
            battle_btn = discord.ui.Button(label="⚔️ Tournament Battle", style=discord.ButtonStyle.danger, row=0)
            async def battle_cb(i: discord.Interaction) -> None:
                if str(i.user.id) != uid:
                    await i.response.send_message("Not your panel.", ephemeral=True)
                    return
                await self._start_tournament_battle(i)
            battle_btn.callback = battle_cb
            view.add_item(battle_btn)

        await smart_reply(interaction, embed=_inf(body), view=view)

    # ── /tournament join ──────────────────────────────────────────

    async def _join_tournament(self, interaction: discord.Interaction) -> None:
        from bot.data.constants import RANK_ORDER
        uid = str(interaction.user.id)

        def mutate(data: dict) -> tuple[bool, str]:
            t    = _t_root(data)
            if not t.get("active"):
                return False, "No active tournament."
            if now_ts() > int(t.get("end_time", 0)):
                return False, "Tournament has ended."
            parts = t.setdefault("participants", {})
            if uid in parts:
                return False, "You are already in this tournament."
            if len(parts) >= int(t.get("max_players", 16)):
                return False, "Tournament is full."

            fee = int(t.get("entry_fee", 0))
            p   = data.get("players", {}).get(uid, {})
            u   = p.get("user", {}) if isinstance(p, dict) else {}
            if not isinstance(u, dict):
                return False, "Player not found."

            min_rank = str(t.get("min_rank", "") or "")
            if min_rank and min_rank in RANK_ORDER:
                player_rank = str(u.get("rank", "Copper") or "Copper")
                player_tier = RANK_ORDER.index(player_rank) if player_rank in RANK_ORDER else 0
                if player_tier < RANK_ORDER.index(min_rank):
                    return False, f"Requires rank **{min_rank}** or higher. You are **{player_rank}**."

            if fee > 0:
                bal = int(u.get("balance", 0))
                if bal < fee:
                    return False, f"Need {fee:,} coins. You have {bal:,}."
                u["balance"] = bal - fee
                t["prize_pool"] = int(t.get("prize_pool", 0)) + fee

            name = str(u.get("name") or u.get("username") or f"<@{uid}>")
            parts[uid] = {"name": name, "xp_earned": 0, "joined_at": now_ts()}
            return True, str(len(parts))

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Join Failed\n│ {result}\n╰────────────────"))
            return

        data = self.bot.storage.load()
        t    = _t_root(data)
        await smart_reply(interaction, embed=_ok(
            f"╭─ ⚔️ Joined Tournament!\n"
            f"│ {t.get('name','Tournament')}\n"
            f"│ 💰 Entry fee: -{int(t.get('entry_fee',0)):,} coins\n"
            f"│ 👥 You are player {result}/{int(t.get('max_players',16))}\n"
            f"│ ⏳ {_time_left(int(t.get('end_time',0)))} remaining\n"
            f"│ Use /tournament battle to earn XP!\n"
            "╰────────────────"
        ))

    # ── /tournament battle ────────────────────────────────────────

    @app_commands.command(name="tournament_battle", description="Battle another tournament participant.")
    async def tournament_battle(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        await self._start_tournament_battle(interaction)

    async def _start_tournament_battle(self, interaction: discord.Interaction) -> None:
        uid  = str(interaction.user.id)
        data = self.bot.storage.load()
        t    = _t_root(data)

        if not t.get("active"):
            await error_reply(interaction, embed=_err("╭─ ❌ No active tournament.\n╰────────────────"))
            return

        parts = t.get("participants", {}) or {}
        if uid not in parts:
            await error_reply(interaction, embed=_err("╭─ ❌ You are not in this tournament.\n│ Use /tournament_join first.\n╰────────────────"))
            return

        # Check if already in battle
        from bot.utils.battle_state import create_battle_state
        battle_root = data.get("battle", {}).get("active_by_user", {})
        if str(battle_root.get(uid, "")):
            await error_reply(interaction, embed=_err("╭─ ❌ You are already in a battle.\n╰────────────────"))
            return

        # Queue into tournament battle — uses same battle system
        # Mark as tournament battle type
        await smart_reply(interaction, embed=_inf(
            f"╭─ ⚔️ Tournament Battle\n"
            f"│ Searching for opponent...\n"
            f"│ Only tournament participants\n"
            f"│ Win XP counts toward leaderboard!\n"
            "╰────────────────"
        ))

        # Trigger the battle cog's queue with tournament flag
        battle_cog = self.bot.cogs.get("BattleCog")
        if battle_cog:
            # Add to tournament queue
            def mutate(d: dict) -> None:
                br = d.setdefault("battle", {})
                tq = br.setdefault("tournament_queue", [])
                if uid not in tq:
                    tq.append(uid)
            self.bot.storage.with_lock(mutate)

            # Schedule auto-match after 15s
            async def try_match() -> None:
                await asyncio.sleep(15)
                data2 = self.bot.storage.load()
                t2    = _t_root(data2)
                parts2 = t2.get("participants", {}) or {}
                tq    = data2.get("battle", {}).get("tournament_queue", [])
                # Find another participant in queue
                opponent = next((p for p in tq if p != uid and p in parts2), None)
                if opponent:
                    def start(d: dict) -> None:
                        tq2 = d.get("battle", {}).get("tournament_queue", [])
                        for p in [uid, opponent]:
                            if p in tq2:
                                tq2.remove(p)
                    self.bot.storage.with_lock(start)
                    ok2, _ = await battle_cog.start_battle_or_fail(
                        interaction, uid, opponent, "tournament"
                    )
                else:
                    # CPU fallback
                    cpu = battle_cog._make_cpu_participant(data2, battle_cog._player_trophies(data2, uid))
                    def remove_q(d: dict) -> None:
                        tq3 = d.get("battle", {}).get("tournament_queue", [])
                        if uid in tq3: tq3.remove(uid)
                    self.bot.storage.with_lock(remove_q)
                    await battle_cog.start_battle_or_fail(
                        interaction, uid, cpu["cpu_key"], "tournament", cpu_opponent=cpu
                    )

            asyncio.create_task(try_match())

    # ── Owner commands ────────────────────────────────────────────

    @app_commands.command(name="o_tournament_create", description="Owner: create a tournament.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_tournament_create(self, interaction: discord.Interaction,
                                   name: str,
                                   duration_hours: app_commands.Range[int, 1, 168] = 24,
                                   entry_fee: app_commands.Range[int, 0, 999_999_999] = 0,
                                   max_players: app_commands.Range[int, 2, 256] = 16,
                                   prize_pool: app_commands.Range[int, 0, 999_999_999] = 0,
                                   min_rank: str = "") -> None:
        from bot.utils.checks import is_owner
        from bot.data.constants import RANK_ORDER
        if not is_owner(interaction):
            await error_reply(interaction, embed=_err("❌ Owner only."))
            return

        min_rank_clean = min_rank.strip().title()
        if min_rank_clean and min_rank_clean not in RANK_ORDER:
            await error_reply(interaction, embed=_err(f"❌ Invalid rank. Choose from: {', '.join(RANK_ORDER)}"))
            return

        def mutate(data: dict) -> tuple[bool, str]:
            t = _t_root(data)
            if t.get("active"):
                return False, "A tournament is already active. Cancel it first."
            t["active"]       = True
            t["name"]         = name.strip()
            t["entry_fee"]    = max(0, entry_fee)
            t["max_players"]  = max(2, max_players)
            t["prize_pool"]   = max(0, prize_pool)
            t["min_rank"]     = min_rank_clean
            t["start_time"]   = now_ts()
            t["end_time"]     = now_ts() + duration_hours * 3600
            t["participants"] = {}
            t["tid"]          = str(uuid.uuid4())[:8]
            return True, "ok"

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Failed\n│ {msg}\n╰────────────────"))
            return

        rank_line = f"│ 🏅 Min Rank: {min_rank_clean}\n" if min_rank_clean else ""
        await smart_reply(interaction, embed=_ok(
            f"╭─ ✅ Tournament Created!\n"
            f"│ ⚔️ {name}\n"
            f"│ ⏳ Duration: {duration_hours}h\n"
            f"│ 💰 Entry: {entry_fee:,} coins\n"
            f"│ 👥 Max: {max_players} players\n"
            f"│ 🏆 Prize Pool: {prize_pool:,} coins\n"
            f"{rank_line}"
            "╰────────────────"
        ), ephemeral=True)

        self._schedule_end(duration_hours * 3600)

    @app_commands.command(name="o_tournament_cancel", description="Owner: cancel tournament and refund fees.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_tournament_cancel(self, interaction: discord.Interaction) -> None:
        from bot.utils.checks import is_owner
        if not is_owner(interaction):
            await error_reply(interaction, embed=_err("❌ Owner only."))
            return

        def mutate(data: dict) -> tuple[bool, int, int]:
            t = _t_root(data)
            if not t.get("active"):
                return False, 0, 0
            fee   = int(t.get("entry_fee", 0))
            parts = t.get("participants", {}) or {}
            total_refunded = 0
            for pid in parts:
                p = data.get("players", {}).get(str(pid), {})
                u = p.get("user", {}) if isinstance(p, dict) else {}
                if isinstance(u, dict) and fee > 0:
                    u["balance"] = int(u.get("balance", 0)) + fee
                    total_refunded += fee
            t["active"]       = False
            t["participants"] = {}
            return True, len(parts), total_refunded

        ok, count, refunded = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err("╭─ ❌ No active tournament.\n╰────────────────"))
            return

        if self._end_task and not self._end_task.done():
            self._end_task.cancel()

        await smart_reply(interaction, embed=_ok(
            f"╭─ 🚫 Tournament Cancelled\n"
            f"│ 💰 {count} players refunded\n"
            f"│ 💰 {refunded:,} coins returned\n"
            "╰────────────────"
        ), ephemeral=True)

    async def _end_tournament(self) -> None:
        """Auto-called when tournament timer expires."""
        def mutate(data: dict) -> tuple[bool, list, int, str]:
            t = _t_root(data)
            if not t.get("active"):
                return False, [], 0, ""
            lb    = _get_leaderboard(t)
            pool  = int(t.get("prize_pool", 0))
            name  = str(t.get("name", "Tournament"))
            results = []
            for i, (uid, pname, xp) in enumerate(lb[:10]):
                if i >= len(PRIZE_SPLIT): break
                prize = int(pool * PRIZE_SPLIT[i])
                p     = data.get("players", {}).get(str(uid), {})
                u     = p.get("user", {}) if isinstance(p, dict) else {}
                if isinstance(u, dict) and prize > 0:
                    u["balance"] = int(u.get("balance", 0)) + prize
                results.append((pname, xp, prize))
            t["active"]       = False
            t["participants"] = {}
            return True, results, pool, name

        ok, results, pool, name = self.bot.storage.with_lock(mutate)
        if not ok:
            return

        data = self.bot.storage.load()
        medals = [e("winner",data), "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        lines  = [f"│ {medals[i]} {pname:<18} {xp:,} XP  +{prize:,} 💰"
                  for i, (pname, xp, prize) in enumerate(results)]

        body = (
            f"╭─ 🏁 Tournament Over!\n"
            f"│ {name}\n"
            f"│ 🏆 Pool: {pool:,} coins distributed\n"
            "│\n"
            + "\n".join(lines)
            + "\n╰────────────────"
        )

        # Announce in all battle channels (best effort)
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if "general" in channel.name.lower() or "battle" in channel.name.lower():
                    try:
                        await channel.send(embed=_ok(body))
                    except Exception:
                        pass
                    break


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TournamentCog(bot))
