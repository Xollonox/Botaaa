"""Discord entry points for the guarded OpenRouter academic AI."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ai import AIQuotaExceeded, AIUnavailable
from neetverse.planner import PlannerError
from neetverse.ui import ERROR, SUCCESS, embed, reply


def plan_embed(payload: dict, *, approved: bool = False) -> discord.Embed:
    lines: list[str] = []
    total = 0
    for index, task in enumerate(payload.get("tasks", []), 1):
        minutes = int(task.get("estimated_minutes", 0))
        total += minutes
        chapter = f" — {task['chapter']}" if task.get("chapter") else ""
        lines.append(
            f"**{index}. {task.get('title', 'Study task')}**\n"
            f"{task.get('subject', 'General')}{chapter} • {minutes} min • P{task.get('priority', 3)}"
        )
    state = "Approved and saved" if approved else "Draft — review before approving"
    description = f"**{state}**\nEstimated total: **{total // 60}h {total % 60}m**\n\n" + "\n\n".join(lines)
    return embed(f"🗓️ {payload.get('title', 'Daily NEET Plan')}", description, color=SUCCESS if approved else 0x6C5CE7)


class PlanProposalView(discord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int, payload: dict) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = str(user_id)
        self.payload = payload

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="This plan proposal belongs to another student.")
            return False
        return True

    @discord.ui.button(label="Approve plan", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            plan = self.bot.planner_service.approve_ai_proposal(
                self.user_id, str(self.payload["proposal_id"])
            )
        except PlannerError as exc:
            await reply(interaction, value=embed("Plan not approved", str(exc), color=ERROR))
            return
        saved = {**self.payload, "tasks": plan["tasks"]}
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(embed=plan_embed(saved, approved=True), view=self)
        self.stop()

    @discord.ui.button(label="Reject", emoji="✖️", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        rejected = self.bot.planner_service.reject_ai_proposal(
            self.user_id, str(self.payload["proposal_id"])
        )
        if not rejected:
            await reply(interaction, value=embed("Proposal unavailable", "It was already resolved.", color=ERROR))
            return
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(
            embed=embed("Plan rejected", "No tasks were added to your planner.", color=ERROR),
            view=self,
        )
        self.stop()


class AIGroup(app_commands.Group):
    def __init__(self, cog: "AICog") -> None:
        super().__init__(name="ai", description="NeetVerse academic AI powered by OpenRouter free models.")
        self.cog = cog

    @app_commands.command(name="tutor", description="Ask the AI tutor using your own academic context.")
    async def tutor(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.cog.bot.academic_ai.tutor(str(interaction.user.id), question)
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await interaction.followup.send(embed=embed("AI unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        value = embed("🧠 NeetVerse Tutor", result.content)
        value.set_footer(text=f"NeetVerse • Free model: {result.model_used}")
        await interaction.followup.send(embed=value, ephemeral=True)

    @app_commands.command(name="daily_plan", description="Ask AI to draft a personalized daily study plan.")
    async def daily_plan(self, interaction: discord.Interaction, request: str = "") -> None:
        profile = self.cog.bot.profile_service.get(str(interaction.user.id))
        if profile is None or profile.get("onboarding_status") != "complete":
            await reply(interaction, value=embed("Profile incomplete", "Complete the required fields in `/start` first.", color=ERROR))
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            _, payload = await self.cog.bot.academic_ai.propose_daily_plan(str(interaction.user.id), request)
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await interaction.followup.send(embed=embed("Plan unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.followup.send(
            embed=plan_embed(payload),
            view=PlanProposalView(self.cog.bot, interaction.user.id, payload),
            ephemeral=True,
        )

    @app_commands.command(name="approve_plan", description="Approve a saved AI proposal after its panel expires.")
    async def approve_plan(self, interaction: discord.Interaction, proposal_id: str) -> None:
        try:
            plan = self.cog.bot.planner_service.approve_ai_proposal(str(interaction.user.id), proposal_id)
        except PlannerError as exc:
            await reply(interaction, value=embed("Plan not approved", str(exc), color=ERROR))
            return
        await reply(interaction, value=plan_embed(plan, approved=True))

    @app_commands.command(name="weekly_review", description="Get an evidence-based review of your current preparation.")
    async def weekly_review(self, interaction: discord.Interaction, request: str = "") -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.cog.bot.academic_ai.weekly_review(str(interaction.user.id), request)
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await interaction.followup.send(embed=embed("Review unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        value = embed("📊 Academic manager review", result.content)
        value.set_footer(text=f"NeetVerse • Free model: {result.model_used}")
        await interaction.followup.send(embed=value, ephemeral=True)

    @app_commands.command(name="mock_analysis", description="Ask AI to analyse your most recently recorded mock.")
    async def mock_analysis(self, interaction: discord.Interaction, request: str = "") -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.cog.bot.academic_ai.analyze_latest_mock(str(interaction.user.id), request)
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await interaction.followup.send(embed=embed("Analysis unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        value = embed("📝 Mock analysis", result.content)
        value.set_footer(text=f"NeetVerse • Free model: {result.model_used}")
        await interaction.followup.send(embed=value, ephemeral=True)


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = AIGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
