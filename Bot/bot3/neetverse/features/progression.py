"""Daily plan, mocks, discipline and privacy-gated ranking entry points."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.mocks import MockError
from neetverse.planner import PlannerError
from neetverse.ui import (
    ERROR,
    SUCCESS,
    duration,
    embed,
    progress_bar,
    reply,
    status_icon,
    subject_icon,
)


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
            f"{status_icon(plan['status'])} `{plan['id'][:8]}` **{plan['title']}**\n"
            f"└ {progress_bar(plan['completed_count'] or 0, plan['task_count'], width=8)} • "
            f"`{plan['completed_count'] or 0}/{plan['task_count']} TASKS` • `{plan['status'].upper()}`"
            for plan in plans
        ]
        await reply(interaction, value=embed("🗂️  Your Study Plan Deck", "\n\n".join(lines) or "📭 No plans yet."))


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
        text = (
            f"🏁 **{result['name']}**\n"
            f"{progress_bar(result['score'], result['max_score'], width=14)}\n"
            f"🎯 **SCORE:** `{result['score']:g}/{result['max_score']:g}` • `{result['percentage']}%`"
        )
        if result["sections"]:
            section = result["sections"][0]
            text += (
                f"\n\n{subject_icon(section['subject'])} **{section['subject']} SECTION**\n"
                f"{progress_bar(section['score'], section['max_score'], width=10)} • "
                f"`{section['score']:g}/{section['max_score']:g}`"
            )
        await reply(interaction, value=embed("📝 Mock recorded", text, color=SUCCESS))

    @app_commands.command(name="history", description="Review recent mock scores and score movement.")
    async def history(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.mock_service.history(str(interaction.user.id))
        lines = []
        for row in rows:
            change = "first recorded" if row["score_change"] is None else f"{row['score_change']:+g} percentage points"
            trend = "🟢" if (row["score_change"] or 0) > 0 else "🔴" if (row["score_change"] or 0) < 0 else "⚪"
            lines.append(
                f"{trend} **{row['name']}** • `{row['score']:g}/{row['max_score']:g}`\n"
                f"└ {progress_bar(row['percentage'], 100, width=8)} • `{change}`"
            )
        await reply(interaction, value=embed("📝  Mock Performance History", "\n\n".join(lines) or "📭 No mocks recorded."))


class RankingGroup(app_commands.Group):
    def __init__(self, cog: "ProgressionCog") -> None:
        super().__init__(name="ranking", description="Control and view opt-in study rankings.")
        self.cog = cog

    @app_commands.command(name="privacy", description="Control public profile and leaderboard visibility.")
    async def privacy(self, interaction: discord.Interaction, visible: bool) -> None:
        profile = self.cog.bot.profile_service.get(str(interaction.user.id))
        if profile is None:
            await reply(interaction, value=embed("No profile", "Run `/start` first.", color=ERROR))
            return
        self.cog.bot.profile_service.update(str(interaction.user.id), {"leaderboard_visible": visible})
        state = "visible" if visible else "private"
        await reply(
            interaction,
            value=embed(
                "Public visibility updated",
                f"Your privacy-safe student card and leaderboard statistics are now **{state}**.",
                color=SUCCESS,
            ),
        )

    @app_commands.command(name="weekly", description="View opted-in students by verified weekly focus time.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.discipline_service.leaderboard()
        if not rows:
            await reply(interaction, value=embed("Weekly ranking", "No students have opted in yet."))
            return
        peak = max(int(row["focus_seconds"]) for row in rows) or 1
        medals = ("🥇", "🥈", "🥉")
        lines = []
        for index, row in enumerate(rows, 1):
            try:
                streak_days = self.cog.bot.streak_service.calculate(str(row["user_id"]))["current"]
            except ValueError:
                streak_days = 0
            lines.append(
                f"{medals[index - 1] if index <= 3 else f'`#{index:02d}`'} **{row['display_name']}**\n"
                f"└ {progress_bar(row['focus_seconds'], peak, width=8, show_percent=False)} • "
                f"`{duration(row['focus_seconds'])}` • 🔥 `{streak_days}d`"
            )
        await interaction.response.send_message(embed=embed("🏆  Weekly Focus League", "\n\n".join(lines)))


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
        completed = sum(task["status"] == "completed" for task in plan["tasks"])
        lines = []
        for task in plan["tasks"]:
            mark = status_icon(task["status"])
            lines.append(
                f"{mark} `{task['id'][:8]}` **{task['title']}**\n"
                f"└ {subject_icon(task.get('subject') or '')} {task.get('subject') or 'General'} • "
                f"`{task.get('estimated_minutes') or '?'} min` • `{task['status'].upper()}`"
            )
        header = (
            f"🎯 **DAILY EXECUTION** {progress_bar(completed, len(plan['tasks']), width=12)}\n"
            f"`{completed}/{len(plan['tasks'])} TASKS COMPLETE`\n\n"
        )
        await reply(
            interaction,
            value=embed(f"🗓️  {plan['title']}", header + ("\n\n".join(lines) or "No tasks.")),
            ephemeral=False,
        )

    @app_commands.command(name="streak", description="Post an automatically calculated verified study streak.")
    @app_commands.describe(student="Optionally view an opted-in server member")
    async def streak(self, interaction: discord.Interaction, student: discord.Member | None = None) -> None:
        target = student or interaction.user
        profile = self.bot.profile_service.get(str(target.id))
        if profile is None:
            await reply(interaction, value=embed("No profile", "Run `/start` first.", color=ERROR))
            return
        if target.id != interaction.user.id and not profile["leaderboard_visible"]:
            await reply(
                interaction,
                value=embed("Private streak", "That student has not enabled public visibility.", color=ERROR),
            )
            return
        try:
            result = self.bot.streak_service.calculate(str(target.id))
        except ValueError as exc:
            await reply(interaction, value=embed("Streak unavailable", str(exc), color=ERROR))
            return
        calendar = " ".join("🔥" if day["active"] else "▫️" for day in result["calendar"])
        calendar_labels = "  ".join(str(day["weekday"]) for day in result["calendar"])
        text = (
            f"🔥 **CURRENT** `{result['current']} DAYS`  •  🏆 **BEST** `{result['longest']} DAYS`\n"
            f"{calendar}\n`{calendar_labels}`\n\n"
            f"⚡ **WEEKLY CONSISTENCY** {progress_bar(result['active_days_week'], 7, width=14)}\n"
            f"⏱️ **Verified focus:** `{duration(result['week_seconds'])}`  •  "
            f"**Today:** `{duration(result['today_seconds'])}`\n\n"
            f"_{result['rule']} Offline manual logs never inflate this card._"
        )
        value = embed(f"🔥  {profile['display_name']} • Streak Reactor", text)
        value.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=value, ephemeral=False)

    @app_commands.command(name="discipline", description="View your transparent recent discipline and lifetime level.")
    async def discipline(self, interaction: discord.Interaction) -> None:
        try:
            result = self.bot.discipline_service.calculate(str(interaction.user.id))
        except ValueError as exc:
            await reply(interaction, value=embed("Discipline unavailable", str(exc), color=ERROR))
            return
        factors = result["factors"]
        text = (
            f"🏅 **{result['tier'].upper()} TIER**  •  `LEVEL {result['level']}`  •  `{result['level_points']} XP`\n"
            f"🔥 **DISCIPLINE CORE** {progress_bar(result['score'], 100, width=14)}\n\n"
            f"📅 **Consistency**\n└ {progress_bar(factors['consistency'], 100, width=10)}\n"
            f"✅ **Plan completion**\n└ {progress_bar(factors['plan_completion'], 100, width=10)}\n"
            f"🔁 **Revision control**\n└ {progress_bar(factors['revision_control'], 100, width=10)}\n"
            f"⚖️ **Subject balance**\n└ {progress_bar(factors['subject_balance'], 100, width=10)}\n\n"
            "_Discipline measures recent behavior—not raw lifetime hours._"
        )
        await reply(interaction, value=embed("🔥  Discipline Power Core", text), ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProgressionCog(bot))
