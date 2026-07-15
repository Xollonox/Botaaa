"""Discord entry points for the guarded OpenRouter academic AI."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ai import AIQuotaExceeded, AIUnavailable
from neetverse.features.voice import SpeakResponseView
from neetverse.planner import PlannerError
from neetverse.ui import ERROR, SUCCESS, embed, progress_bar, reply, subject_icon


def plan_embed(payload: dict, *, approved: bool = False) -> discord.Embed:
    lines: list[str] = []
    tasks = payload.get("tasks", [])
    total = sum(int(task.get("estimated_minutes", 0)) for task in tasks)
    priority_icons = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🔵", 5: "⚪"}
    for index, task in enumerate(tasks, 1):
        minutes = int(task.get("estimated_minutes", 0))
        chapter = f" — {task['chapter']}" if task.get("chapter") else ""
        lines.append(
            f"{priority_icons.get(int(task.get('priority', 3)), '⚪')} `#{index:02d}` "
            f"{subject_icon(task.get('subject', ''))} **{task.get('title', 'Study task')}**\n"
            f"└ {task.get('subject', 'General')}{chapter} • `{minutes} min` • "
            f"{progress_bar(minutes, total, width=6, show_percent=False)}"
        )
    state = "✅ APPROVED & SAVED" if approved else "🟣 AI DRAFT • REVIEW REQUIRED"
    description = (
        f"`{state}`\n"
        f"⏳ **TOTAL LOAD:** `{total // 60}h {total % 60}m` • `{len(tasks)} missions`\n\n"
        + "\n\n".join(lines)
    )
    return embed(f"🗓️  {payload.get('title', 'Daily NEET Plan')}", description, color=SUCCESS if approved else 0x6C5CE7)


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
    async def tutor(self, interaction: discord.Interaction, question: str, private: bool = False) -> None:
        await interaction.response.defer(ephemeral=private, thinking=True)
        try:
            result = await self.cog.bot.academic_ai.tutor(str(interaction.user.id), question)
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await interaction.followup.send(embed=embed("AI unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        value = embed("🧠 NeetVerse Tutor", result.content)
        value.set_footer(text=f"NeetVerse • Free model: {result.model_used}")
        await interaction.followup.send(
            embed=value,
            view=SpeakResponseView(
                self.cog.bot, interaction.user.id, result.content, title=question
            ),
            ephemeral=private,
        )

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.bot.user is None:
            return
        direct_message = message.guild is None
        mentioned = self.bot.user in message.mentions
        if not direct_message and not mentioned:
            return
        question = re.sub(
            rf"<@!?{self.bot.user.id}>", "", message.content or "", flags=re.IGNORECASE
        ).strip()
        if not question:
            await message.reply(
                "🧠 **NEETVERSE AI** • Mention me with a NEET question, or use `/ai tutor`.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        try:
            async with message.channel.typing():
                result = await self.bot.academic_ai.tutor(str(message.author.id), question)
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await message.reply(
                embed=embed("AI unavailable", str(exc), color=ERROR),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        value = embed("🧠 NeetVerse Tutor", result.content)
        value.set_footer(text=f"NeetVerse • Free model: {result.model_used}")
        view = None
        if message.guild is not None:
            view = SpeakResponseView(
                self.bot, message.author.id, result.content, title=question
            )
        await message.reply(
            embed=value,
            view=view,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
