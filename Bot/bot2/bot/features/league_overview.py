"""League overview commands."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.utils.ui import box, e, make_embed


def _league_from_trophies(trophies: int) -> str:
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


LEAGUE_ORDER: list[tuple[str, str]] = [
    ("Copper", "0-200"),
    ("Iron", "200-400"),
    ("Bronze", "400-800"),
    ("Silver", "800-1200"),
    ("Gold", "1200-1600"),
    ("Diamond", "1600-2400"),
    ("Platinum", "2400-3200"),
    ("Sapphire", "3200-4000"),
    ("Ruby", "4000+"),
]


class LeagueOverviewCog(commands.Cog):
    league = app_commands.Group(name="league", description="League commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @league.command(name="overview", description="View league thresholds and player distribution.")
    async def overview(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return

        data = self.bot.storage.load()
        players = data.get("players", {})
        counts: dict[str, int] = {name: 0 for name, _ in LEAGUE_ORDER}

        total_players = 0
        if isinstance(players, dict):
            for player in players.values():
                if not isinstance(player, dict):
                    continue
                user = player.get("user", {})
                if not isinstance(user, dict):
                    continue
                total_players += 1
                trophies = int(user.get("trophies", 0))
                league_name = _league_from_trophies(trophies)
                counts[league_name] = counts.get(league_name, 0) + 1

        threshold_lines: list[str] = []
        count_lines: list[str] = []
        for name, band in LEAGUE_ORDER:
            icon = e(name.lower(), data)
            if icon == "•":
                icon = e("league", data)
            threshold_lines.append(f"{icon} {name}: {band}")
            count_lines.append(f"{icon} {name}: {counts.get(name, 0)}")

        body = (
            box("Trophy Thresholds", threshold_lines) + "\n\n" +
            box("League Distribution", count_lines) + "\n\n" +
            box("Summary", [f"👥 Total Players: {total_players}"])
        )
        embed = make_embed(data, f"{e('league', data)} League Overview", body)
        await smart_reply(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeagueOverviewCog(bot))
