"""Daily plan, mocks, discipline and privacy-gated ranking entry points."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.mocks import MockError
from neetverse.planner import PlannerError
from neetverse.ui import ERROR, SUCCESS, duration, embed, reply


class TaskGroup(app_commands.Group):
    def __init__(self, cog: "ProgressionCog") -> None:
        super().__init__(name="task", description="Manage tasks from your approved study plan.")
        self.cog = cog

    @app_commands.command(name="complete", description="Complete a task using the ID shown in /today.")
    async def complete(self, interaction: discord.Interaction, task_id: str) -> None:
        try:
            task = self.cog.bot.planner_service.complete_task(str(interaction.user.id), task_id)
        except PlannerError as exc:
            await reply(interaction, value=embed("Task not completed", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("✅ Task completed", f"**{task['title']}**", color=SUCCESS))


class PlanGroup(app_commands.Group):
    def __init__(self, cog: "ProgressionCog") -> None:
        super().__init__(name="plan", description="Build and inspect study plans without requiring AI.")
        self.cog = cog

    @app_commands.command(name="create", description="Create your own dated study plan.")
    @app_commands.choices(period=[
        app_commands.Choice(name="Daily", value="daily"),
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Monthly", value="monthly"),
        app_commands.Choice(name="Roadmap", value="roadmap"),
        app_commands.Choice(name="Custom", value="custom"),
    ])
    async def create(self, interaction: discord.Interaction, title: str, period: app_commands.Choice[str], starts_on: str, ends_on: str) -> None:
        try:
            plan = self.cog.bot.planner_service.create_manual_plan(
                str(interaction.user.id), title=title, period_type=period.value,
                starts_on=starts_on, ends_on=ends_on,
            )
        except PlannerError as exc:
            await reply(interaction, value=embed("Plan not created", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Plan created", f"`{plan['id'][:8]}` **{plan['title']}**\n{plan['starts_on']} to {plan['ends_on']}", color=SUCCESS))

    @app_commands.command(name="add_task", description="Add a task to one of your active plans.")
    async def add_task(
        self, interaction: discord.Interaction, plan_id: str, title: str,
        subject: str = "", chapter: str = "", activity: str = "",
        estimated_minutes: app_commands.Range[int, 1, 1440] | None = None,
        priority: app_commands.Range[int, 1, 5] = 3,
    ) -> None:
        try:
            task = self.cog.bot.planner_service.add_task(
                str(interaction.user.id), plan_id, title=title, subject=subject,
                chapter=chapter, activity=activity, estimated_minutes=estimated_minutes,
                priority=int(priority),
            )
        except PlannerError as exc:
            await reply(interaction, value=embed("Task not added", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Task added", f"`{task['id'][:8]}` **{task['title']}**", color=SUCCESS))

    @app_commands.command(name="list", description="List your recent study plans and completion counts.")
    async def list_plans(self, interaction: discord.Interaction) -> None:
        plans = self.cog.bot.planner_service.list_plans(str(interaction.user.id))
        lines = [
            f"`{plan['id'][:8]}` **{plan['title']}** — {plan['completed_count'] or 0}/{plan['task_count']} tasks • {plan['status']}"
            for plan in plans
        ]
        await reply(interaction, value=embed("Your study plans", "\n".join(lines) or "No plans yet."))


class MockGroup(app_commands.Group):
    def __init__(self, cog: "ProgressionCog") -> None:
        super().__init__(name="mock", description="Record and analyse NEET mock tests.")
        self.cog = cog

    @app_commands.command(name="log", description="Record a mock result and optional subject section.")
    async def log(
        self,
        interaction: discord.Interaction,
        name: str,
        score: app_commands.Range[float, 0, 720],
        max_score: app_commands.Range[float, 1, 720] = 720,
        scope: str = "Full syllabus",
        source: str = "",
        subject: str = "",
        subject_score: app_commands.Range[float, 0, 360] | None = None,
        subject_max_score: app_commands.Range[float, 1, 360] | None = None,
    ) -> None:
        sections = None
        if subject or subject_score is not None or subject_max_score is not None:
            if not subject or subject_score is None or subject_max_score is None:
                await reply(interaction, value=embed("Mock not saved", "Provide subject, subject score, and subject maximum together.", color=ERROR))
                return
            sections = [{"subject": subject, "score": subject_score, "max_score": subject_max_score}]
        try:
            result = self.cog.bot.mock_service.record(
                str(interaction.user.id), name=name, score=score, max_score=max_score,
                scope=scope, source=source or None, sections=sections,
            )
        except MockError as exc:
            await reply(interaction, value=embed("Mock not saved", str(exc), color=ERROR))
            return
        text = f"Score: **{result['score']:g}/{result['max_score']:g}**\nPercentage: **{result['percentage']}%**"
        if result["sections"]:
            section = result["sections"][0]
            text += f"\n{section['subject']}: **{section['score']:g}/{section['max_score']:g}**"
        await reply(interaction, value=embed("📝 Mock recorded", text, color=SUCCESS))

    @app_commands.command(name="history", description="Review recent mock scores and score movement.")
    async def history(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.mock_service.history(str(interaction.user.id))
        lines = []
        for row in rows:
            change = "first recorded" if row["score_change"] is None else f"{row['score_change']:+g} percentage points"
            lines.append(f"**{row['name']}** — {row['score']:g}/{row['max_score']:g} ({row['percentage']:g}%) • {change}")
        await reply(interaction, value=embed("📝 Mock history", "\n".join(lines) or "No mocks recorded."))


class RankingGroup(app_commands.Group):
    def __init__(self, cog: "ProgressionCog") -> None:
        super().__init__(name="ranking", description="Control and view opt-in study rankings.")
        self.cog = cog

    @app_commands.command(name="privacy", description="Choose whether your study time appears on leaderboards.")
    async def privacy(self, interaction: discord.Interaction, visible: bool) -> None:
        profile = self.cog.bot.profile_service.get(str(interaction.user.id))
        if profile is None:
            await reply(interaction, value=embed("No profile", "Run `/start` first.", color=ERROR))
            return
        self.cog.bot.profile_service.update(str(interaction.user.id), {"leaderboard_visible": visible})
        state = "visible" if visible else "private"
        await reply(interaction, value=embed("Ranking privacy updated", f"Your leaderboard statistics are now **{state}**.", color=SUCCESS))

    @app_commands.command(name="weekly", description="View opted-in students by verified weekly focus time.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.discipline_service.leaderboard()
        if not rows:
            await reply(interaction, value=embed("Weekly ranking", "No students have opted in yet."))
            return
        lines = [f"**{index}. {row['display_name']}** — {duration(row['focus_seconds'])}" for index, row in enumerate(rows, 1)]
        await interaction.response.send_message(embed=embed("🏆 Weekly verified focus", "\n".join(lines)))


class ProgressionCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.groups = [TaskGroup(self), PlanGroup(self), MockGroup(self), RankingGroup(self)]
        for group in self.groups:
            self.bot.tree.add_command(group)

    async def cog_unload(self) -> None:
        for group in self.groups:
            self.bot.tree.remove_command(group.name, type=group.type)

    @app_commands.command(name="today", description="View your currently approved daily plan.")
    async def today(self, interaction: discord.Interaction) -> None:
        plan = self.bot.planner_service.active_daily_plan(str(interaction.user.id))
        if plan is None:
            await reply(interaction, value=embed("Today", "No active daily plan. Create a draft with `/ai daily_plan`."))
            return
        lines = []
        for task in plan["tasks"]:
            mark = "✅" if task["status"] == "completed" else "⬜"
            lines.append(
                f"{mark} `{task['id'][:8]}` **{task['title']}**\n"
                f"{task.get('subject') or 'General'} • {task.get('estimated_minutes') or '?'} min • {task['status']}"
            )
        await reply(interaction, value=embed(f"🗓️ {plan['title']}", "\n\n".join(lines) or "No tasks."))

    @app_commands.command(name="discipline", description="View your transparent recent discipline and lifetime level.")
    async def discipline(self, interaction: discord.Interaction) -> None:
        try:
            result = self.bot.discipline_service.calculate(str(interaction.user.id))
        except ValueError as exc:
            await reply(interaction, value=embed("Discipline unavailable", str(exc), color=ERROR))
            return
        factors = result["factors"]
        text = (
            f"**Tier:** {result['tier']}\n**Score:** {result['score']}/100\n"
            f"**Study level:** {result['level']} ({result['level_points']} points)\n\n"
            f"Consistency: {factors['consistency']}%\n"
            f"Plan completion: {factors['plan_completion']}%\n"
            f"Revision control: {factors['revision_control']}%\n"
            f"Subject balance: {factors['subject_balance']}%\n\n"
            "Discipline measures recent behavior, not raw lifetime hours."
        )
        await reply(interaction, value=embed("🔥 Discipline", text))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProgressionCog(bot))
