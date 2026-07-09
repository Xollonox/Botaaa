"""Leaderboard commands."""

from __future__ import annotations

import logging
from math import ceil
from typing import Any

import discord
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.season_logic import LEAGUE_ORDER
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply

logger = logging.getLogger(__name__)


class LeaderboardPanel(discord.ui.View):
    def __init__(self, cog: "LeaderboardsCog", user_id: int, rows: list[dict], title: str, icon: str, data: dict | None = None) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.rows = rows
        self.title = title
        self.icon = icon
        self.page = 1
        self.page_size = 10
        self.message: discord.Message | None = None
        self._data = data if data is not None else cog.bot.storage.load()
        self._sync()

    def _sync(self) -> None:
        total = max(1, -(-len(self.rows) // self.page_size))
        self.prev_btn.disabled = self.page <= 1
        self.next_btn.disabled = self.page >= total

    @property
    def total_pages(self) -> int:
        return max(1, -(-len(self.rows) // self.page_size))

    def build_embed(self, data: dict) -> discord.Embed:
        start = (self.page - 1) * self.page_size
        chunk = self.rows[start: start + self.page_size]
        lines = []
        for idx, row in enumerate(chunk, start=start + 1):
            trophies = int(row.get("trophies", 0))
            name = row.get("name", row.get("user_id", "?"))
            rank = row.get("rank", "")
            extra = f" · {rank}" if rank else ""
            lines.append(f"{idx}. {name}{extra} · 🏆 {trophies}")
        if not lines:
            lines = ["No data yet."]
        body = box(f"{self.title} — Page {self.page}/{self.total_pages}", lines)
        embed = make_embed(None, "LOOKISM HXCC • LEADERBOARD", body, color=0xE11D48, footer="Rankings")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await error_reply(interaction, "Not your panel.")
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.exception("Failed to disable leaderboard panel after timeout")

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page -= 1
        self._sync()
        data = self._data
        await interaction.response.edit_message(embed=self.build_embed(data), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        self._sync()
        data = self._data
        await interaction.response.edit_message(embed=self.build_embed(data), view=self)

    @discord.ui.button(label="🏅 League Overview", style=discord.ButtonStyle.secondary, row=1)
    async def league_overview_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self._data
        players = data.get("players", {})
        league_order = [
            ("Copper", "0-200"), ("Iron", "200-400"), ("Bronze", "400-800"),
            ("Silver", "800-1200"), ("Gold", "1200-1600"), ("Diamond", "1600-2400"),
            ("Platinum", "2400-3200"), ("Sapphire", "3200-4000"), ("Ruby", "4000+"),
        ]
        def _league_from_trophies(t: int) -> str:
            if t >= 4000: return "Ruby"
            if t >= 3200: return "Sapphire"
            if t >= 2400: return "Platinum"
            if t >= 1600: return "Diamond"
            if t >= 1200: return "Gold"
            if t >= 800:  return "Silver"
            if t >= 400:  return "Bronze"
            if t >= 200:  return "Iron"
            return "Copper"
        counts: dict[str, int] = {name: 0 for name, _ in league_order}
        total_players = 0
        if isinstance(players, dict):
            for player in players.values():
                if not isinstance(player, dict): continue
                user = player.get("user", {})
                if not isinstance(user, dict): continue
                total_players += 1
                counts[_league_from_trophies(int(user.get("trophies", 0)))] = counts.get(_league_from_trophies(int(user.get("trophies", 0))), 0) + 1
        from bot.utils.ui import box
        threshold_lines = [f"{e(n.lower(), data) or '•'} {n}: {band}" for n, band in league_order]
        count_lines = [f"{e(n.lower(), data) or '•'} {n}: {counts.get(n, 0)}" for n, _ in league_order]
        body = box("Trophy Thresholds", threshold_lines) + "\n\n" + box("League Distribution", count_lines) + "\n\n" + box("Summary", [f"👥 Total Players: {total_players}"])
        embed = make_embed(data, f"{e('league', data)} League Overview", body)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class LeaderboardsCog(commands.Cog):
    @commands.group(name="lb", invoke_without_subcommand=True)
    async def lb(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _player_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        players = data.get("players", {})
        out = []
        if isinstance(players, dict):
            for uid, player in players.items():
                if not isinstance(player, dict):
                    continue
                user = player.get("user", {})
                if not isinstance(user, dict):
                    continue
                out.append(
                    {
                        "user_id": str(uid),
                        "name": str(user.get("name", uid)),
                        "rank": str(user.get("rank", "Copper")),
                        "trophies": int(user.get("trophies", 0)),
                    }
                )
        out.sort(key=lambda x: x["trophies"], reverse=True)
        return out

    async def _send_player_page(self, ctx: commands.Context, data: dict[str, Any], rows: list[dict[str, Any]], title: str, page: int) -> None:
        panel = LeaderboardPanel(self, ctx.author.id, rows, title, e("leaderboard", data), data)
        panel.page = max(1, min(int(page), panel.total_pages))
        panel._sync()
        if not rows:
            await smart_reply(ctx, embed=make_embed(data, f"{e('leaderboard', data)} {title}", "No data yet."))
            return
        panel.message = await smart_reply(ctx, embed=panel.build_embed(data), view=panel)

    async def _send_simple_rows(
        self,
        ctx: commands.Context,
        data: dict[str, Any],
        rows: list[dict[str, Any]],
        title: str,
        icon: str,
        page: int,
    ) -> None:
        panel = LeaderboardPanel(self, ctx.author.id, rows, title, icon, data)
        panel.page = max(1, min(int(page), panel.total_pages))
        panel._sync()
        if not rows:
            await smart_reply(ctx, embed=make_embed(data, f"{icon} {title}", "No data yet."))
            return
        panel.message = await smart_reply(ctx, embed=panel.build_embed(data), view=panel)

    @lb.command(name="global")
    async def lb_global(self, ctx: commands.Context, page: int = 1) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return
        data = self.bot.storage.load()
        await self._send_player_page(ctx, data, self._player_rows(data), "Global", page)

    @lb.command(name="league")
    async def lb_league(self, ctx: commands.Context, league_name: str, page: int = 1) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return
        data = self.bot.storage.load()
        league = str(league_name).strip()
        rows = [row for row in self._player_rows(data) if row.get("rank") == league]
        await self._send_player_page(ctx, data, rows, f"League: {league}", page)

    @lb.command(name="gang")
    async def lb_gang(self, ctx: commands.Context, page: int = 1) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return
        data = self.bot.storage.load()

        gangs = data.get("gangs", {})
        if not isinstance(gangs, dict) or not gangs:
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('gang', data)} Gang Leaderboard", "No gang data yet."), ephemeral=True
            )
            return

        rows = []
        players = data.get("players", {})
        for gang_id, gang in gangs.items():
            if not isinstance(gang, dict):
                continue
            members = gang.get("members", [])
            if not isinstance(members, list):
                members = []
            total = 0
            for uid in members:
                p = players.get(str(uid), {}) if isinstance(players, dict) else {}
                u = p.get("user", {}) if isinstance(p, dict) else {}
                if isinstance(u, dict):
                    total += int(u.get("trophies", 0))
            rows.append({"name": str(gang.get("name", gang_id)), "trophies": total})

        rows.sort(key=lambda x: x["trophies"], reverse=True)
        await self._send_simple_rows(ctx, data, rows, "Gang", e("gang", data), page)

    @lb.command(name="alliance")
    async def lb_alliance(self, ctx: commands.Context, page: int = 1) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return
        data = self.bot.storage.load()

        alliances = data.get("alliances", {})
        if not isinstance(alliances, dict) or not alliances:
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('alliance', data)} Alliance Leaderboard", "No alliance data yet."), ephemeral=True
            )
            return

        gangs = data.get("gangs", {})
        players = data.get("players", {})
        rows = []
        for alliance_id, alliance in alliances.items():
            if not isinstance(alliance, dict):
                continue
            gang_ids = alliance.get("gang_ids", alliance.get("gangs", []))
            if not isinstance(gang_ids, list):
                gang_ids = []
            total = 0
            for gid in gang_ids:
                gang = gangs.get(str(gid), {}) if isinstance(gangs, dict) else {}
                members = gang.get("members", []) if isinstance(gang, dict) else []
                if not isinstance(members, list):
                    continue
                for uid in members:
                    p = players.get(str(uid), {}) if isinstance(players, dict) else {}
                    u = p.get("user", {}) if isinstance(p, dict) else {}
                    if isinstance(u, dict):
                        total += int(u.get("trophies", 0))
            rows.append({"name": str(alliance.get("name", alliance_id)), "trophies": total})

        rows.sort(key=lambda x: x["trophies"], reverse=True)
        await self._send_simple_rows(ctx, data, rows, "Alliance", e("alliance", data), page)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardsCog(bot))
