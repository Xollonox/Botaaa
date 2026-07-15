"""Discord-native measurable goal management."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.goals import GoalError
from neetverse.ui import ERROR, SUCCESS, embed, reply


class GoalGroup(app_commands.Group):
    def __init__(self, cog: "GoalCog") -> None:
        super().__init__(name="goal", description="Set and track measurable preparation goals.")
        self.cog = cog

    @app_commands.command(name="create", description="Create a measurable personal study goal.")
    async def create(
        self,
        interaction: discord.Interaction,
        title: str,
        metric: str,
        target_value: app_commands.Range[float, 0.01, 10_000_000.0],
        unit: str,
        subject: str = "",
        due_date: str = "",
        remind: bool = False,
    ) -> None:
        try:
            goal = self.cog.bot.goal_service.create(
                str(interaction.user.id), title=title, metric=metric,
                target_value=float(target_value), unit=unit, subject=subject,
                due_date=due_date or None, remind=remind,
            )
        except GoalError as exc:
            await reply(interaction, value=embed("Goal not created", str(exc), color=ERROR))
            return
        due = f"\nDue: <t:{goal['due_at']}:D>" if goal["due_at"] else ""
        await reply(interaction, value=embed(
            "🎯 Goal created",
            f"`{goal['id'][:8]}` **{goal['title']}**\nTarget: {goal['target_value']:g} {goal['unit']}{due}",
            color=SUCCESS,
        ))

    @app_commands.command(name="list", description="Show your active goals.")
    async def list_goals(self, interaction: discord.Interaction) -> None:
        goals = self.cog.bot.goal_service.list(str(interaction.user.id))
        lines = [
            f"`{goal['id'][:8]}` **{goal['title']}** — {goal['current_value']:g}/{goal['target_value']:g} {goal['unit']} ({goal['progress_percent']:g}%)"
            for goal in goals
        ]
        await reply(interaction, value=embed("🎯 Your goals", "\n".join(lines) or "No active goals."))

    @app_commands.command(name="progress", description="Set the current value of one of your goals.")
    async def progress(self, interaction: discord.Interaction, goal_id: str, current_value: app_commands.Range[float, 0.0, 10_000_000.0]) -> None:
        try:
            goal = self.cog.bot.goal_service.set_progress(str(interaction.user.id), goal_id, float(current_value))
        except GoalError as exc:
            await reply(interaction, value=embed("Goal not updated", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed(
            "Goal completed" if goal["status"] == "completed" else "Goal updated",
            f"**{goal['title']}** — {goal['current_value']:g}/{goal['target_value']:g} {goal['unit']} ({goal['progress_percent']:g}%)",
            color=SUCCESS,
        ))

    @app_commands.command(name="cancel", description="Cancel one of your active goals.")
    async def cancel(self, interaction: discord.Interaction, goal_id: str) -> None:
        try:
            goal = self.cog.bot.goal_service.cancel(str(interaction.user.id), goal_id)
        except GoalError as exc:
            await reply(interaction, value=embed("Goal not cancelled", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Goal cancelled", f"**{goal['title']}**", color=SUCCESS))


class GoalCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = GoalGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GoalCog(bot))
