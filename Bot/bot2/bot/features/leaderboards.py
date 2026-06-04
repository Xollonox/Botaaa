"""Leaderboard commands."""

from __future__ import annotations

import logging
from math import ceil
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.season_logic import LEAGUE_ORDER
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply

logger = logging.getLogger(__name__)


class LeaderboardPanel(discord.ui.View):
    def __init__(self, cog: "LeaderboardsCog", user_id: int, rows: list[dict], title: str, icon: str) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.rows = rows
        self.title = title
        self.icon = icon
        self.page = 1
        self.page_size = 10
        self.message: discord.Message | None = None
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
        data = self.cog.bot.storage.load()
        await interaction.response.edit_message(embed=self.build_embed(data), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        self._sync()
        data = self.cog.bot.storage.load()
        await interaction.response.edit_message(embed=self.build_embed(data), view=self)


class LeaderboardsCog(commands.Cog):
    lb = app_commands.Group(name="lb", description="Leaderboard commands")

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

    async def _send_player_page(self, interaction: discord.Interaction, data: dict[str, Any], rows: list[dict[str, Any]], title: str, page: int) -> None:
        panel = LeaderboardPanel(self, interaction.user.id, rows, title, e("leaderboard", data))
        panel.page = max(1, min(int(page), panel.total_pages))
        panel._sync()
        if not rows:
            await smart_reply(interaction, embed=make_embed(data, f"{e('leaderboard', data)} {title}", "No data yet."))
            return
        await smart_reply(interaction, embed=panel.build_embed(data), view=panel)
        panel.message = await interaction.original_response()

    async def _send_simple_rows(
        self,
        interaction: discord.Interaction,
        data: dict[str, Any],
        rows: list[dict[str, Any]],
        title: str,
        icon: str,
        page: int,
    ) -> None:
        panel = LeaderboardPanel(self, interaction.user.id, rows, title, icon)
        panel.page = max(1, min(int(page), panel.total_pages))
        panel._sync()
        if not rows:
            await smart_reply(interaction, embed=make_embed(data, f"{icon} {title}", "No data yet."))
            return
        await smart_reply(interaction, embed=panel.build_embed(data), view=panel)
        panel.message = await interaction.original_response()

    @lb.command(name="global", description="Global trophy leaderboard")
    async def lb_global(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, None] = 1) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        await self._send_player_page(interaction, data, self._player_rows(data), "Global", int(page))

    @lb.command(name="league", description="League leaderboard")
    async def lb_league(self, interaction: discord.Interaction, league_name: str, page: app_commands.Range[int, 1, None] = 1) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        league = str(league_name).strip()
        rows = [row for row in self._player_rows(data) if row.get("rank") == league]
        await self._send_player_page(interaction, data, rows, f"League: {league}", int(page))

    @lb_league.autocomplete("league_name")
    async def _league_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=name, value=name) for name in LEAGUE_ORDER if current.lower() in name.lower()][:25]

    @lb.command(name="gang", description="Gang leaderboard")
    async def lb_gang(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, None] = 1) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()

        gangs = data.get("gangs", {})
        if not isinstance(gangs, dict) or not gangs:
            await smart_reply(interaction, 
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
        await self._send_simple_rows(interaction, data, rows, "Gang", e("gang", data), int(page))

    @lb.command(name="alliance", description="Alliance leaderboard")
    async def lb_alliance(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, None] = 1) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()

        alliances = data.get("alliances", {})
        if not isinstance(alliances, dict) or not alliances:
            await smart_reply(interaction, 
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
        await self._send_simple_rows(interaction, data, rows, "Alliance", e("alliance", data), int(page))


async def setup(bot: commands.Bot) -> None:
    # NOTE: do NOT call bot.tree.add_command(cog.lb) here — add_cog auto-registers it.
    await bot.add_cog(LeaderboardsCog(bot))
