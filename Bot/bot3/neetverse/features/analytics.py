"""Weekly and monthly evidence-based progress summaries."""

from __future__ import annotations

from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ui import ERROR, duration, embed, progress_bar, reply, sparkline, subject_icon


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
        accuracy = data["question_accuracy"]
        mock = data["average_mock_percent"]
        subjects = "\n".join(
            f"{subject_icon(subject)} **{subject}** • `{duration(seconds)}`\n"
            f"└ {progress_bar(seconds, data['focus_seconds'], width=7)}"
            for subject, seconds in list(data["by_subject"].items())[:8]
        ) or "No completed focus sessions."
        start = date.fromisoformat(data["starts_on"])
        daily_values = [
            int(data["by_day"].get((start + timedelta(days=offset)).isoformat(), 0))
            for offset in range(data["days"])
        ]
        activity_graph = sparkline(daily_values)
        body = (
            f"`{data['starts_on']}  →  {data['ends_on']}`\n"
            f"📅 **ACTIVE DAYS** {progress_bar(data['active_days'], data['days'], width=12)}\n"
            f"📈 **FOCUS TREND** `{activity_graph}`"
        )
        value = embed(f"📈  {title} • Performance HUD", body)
        value.add_field(
            name="⚡ FOCUS OUTPUT",
            value=(
                f"**{duration(data['focus_seconds'])}** • `{data['sessions']} sessions`\n"
                f"Average `{duration(data['average_focus_per_active_day'])}` / active day"
            ),
            inline=False,
        )
        value.add_field(
            name="🎯 QUESTION ACCURACY",
            value=(
                f"{progress_bar(accuracy, 100, width=9)}\n`{data['questions_attempted']} attempted`"
                if accuracy is not None else "`No questions logged`"
            ),
            inline=True,
        )
        value.add_field(
            name="📝 MOCK AVERAGE",
            value=(
                f"{progress_bar(mock, 100, width=9)}\n`{data['mocks_completed']} mocks`"
                if mock is not None else "`No mocks logged`"
            ),
            inline=True,
        )
        value.add_field(
            name="🔁 REVISION CONTROL",
            value=f"`{data['revisions_completed']} completed`",
            inline=True,
        )
        value.add_field(name="⚖️ SUBJECT BALANCE", value=subjects, inline=False)
        await reply(interaction, value=value, ephemeral=False)


class AnalyticsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = StatsGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnalyticsCog(bot))
