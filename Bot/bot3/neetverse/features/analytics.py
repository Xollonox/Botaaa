"""Weekly and monthly evidence-based progress summaries."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ui import ERROR, duration, embed, reply


class StatsGroup(app_commands.Group):
    def __init__(self, cog: "AnalyticsCog") -> None:
        super().__init__(name="stats", description="Review detailed study trends from canonical records.")
        self.cog = cog

    @app_commands.command(name="weekly", description="Show the last seven local calendar days.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, 7, "Weekly progress")

    @app_commands.command(name="monthly", description="Show the last thirty local calendar days.")
    async def monthly(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, 30, "Monthly progress")

    async def _show(self, interaction: discord.Interaction, days: int, title: str) -> None:
        try:
            data = self.cog.bot.analytics_service.period(str(interaction.user.id), days=days)
        except ValueError as exc:
            await reply(interaction, value=embed("Stats unavailable", str(exc), color=ERROR))
            return
        accuracy = "No questions" if data["question_accuracy"] is None else f"{data['question_accuracy']}% accuracy"
        mock = "No mocks" if data["average_mock_percent"] is None else f"{data['average_mock_percent']}% average"
        subjects = "\n".join(
            f"• {subject}: **{duration(seconds)}**" for subject, seconds in list(data["by_subject"].items())[:8]
        ) or "No completed focus sessions."
        body = (
            f"**{data['starts_on']} to {data['ends_on']}**\n"
            f"Focus: **{duration(data['focus_seconds'])}** across {data['sessions']} sessions\n"
            f"Active days: **{data['active_days']}/{data['days']}** • average {duration(data['average_focus_per_active_day'])}/active day\n"
            f"Questions: **{data['questions_attempted']}** • {accuracy}\n"
            f"Revisions completed: **{data['revisions_completed']}**\n"
            f"Mocks: **{data['mocks_completed']}** • {mock}\n\n"
            f"**Subject balance**\n{subjects}"
        )
        await reply(interaction, value=embed(f"📈 {title}", body))


class AnalyticsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = StatsGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnalyticsCog(bot))
