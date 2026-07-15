"""Discord entry points for practice, mistakes, revision, resources and progress."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.coverage import CoverageError
from neetverse.practice import PracticeError
from neetverse.revision import RevisionError
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


class PracticeGroup(app_commands.Group):
    def __init__(self, cog: "AcademicsCog") -> None:
        super().__init__(name="practice", description="Track NEET question practice.")
        self.cog = cog

    @app_commands.command(name="log", description="Record a completed question-practice batch.")
    async def log(
        self,
        interaction: discord.Interaction,
        subject: str,
        attempted: app_commands.Range[int, 1, 1000],
        correct: app_commands.Range[int, 0, 1000],
        incorrect: app_commands.Range[int, 0, 1000],
        skipped: app_commands.Range[int, 0, 1000],
        chapter: str = "",
        source: str = "",
        duration_minutes: app_commands.Range[int, 0, 1440] | None = None,
    ) -> None:
        try:
            result = self.cog.bot.practice_service.record(
                str(interaction.user.id), subject=subject, chapter=chapter or None,
                attempted=attempted, correct=correct, incorrect=incorrect, skipped=skipped,
                source=source or None, duration_minutes=duration_minutes,
            )
        except PracticeError as exc:
            await reply(interaction, value=embed("Practice not saved", str(exc), color=ERROR))
            return
        text = (
            f"{subject_icon(subject)} **{subject.upper()} PRACTICE RUN**\n"
            f"🎯 Accuracy {progress_bar(result['accuracy'], 100, width=12)}\n\n"
            f"✅ **{result['correct']} correct**  •  ❌ **{result['incorrect']} incorrect**  •  "
            f"⏭️ **{result['skipped']} skipped**\n"
            f"📦 `{result['attempted']} total questions`\n\n"
            f"🧠 **MASTERY ESTIMATE**\n"
            f"{progress_bar(result['subject_mastery']['score'], 100, width=12)}\n"
            f"Evidence confidence: **{result['subject_mastery']['confidence'] * 100:.0f}%**"
        )
        await reply(interaction, value=embed("Practice recorded", text, color=SUCCESS))


class MistakeGroup(app_commands.Group):
    def __init__(self, cog: "AcademicsCog") -> None:
        super().__init__(name="mistake", description="Maintain your personal mistake book.")
        self.cog = cog

    @app_commands.command(name="add", description="Add a mistake and schedule its first revision.")
    async def add(
        self,
        interaction: discord.Interaction,
        subject: str,
        category: str,
        chapter: str = "",
        topic: str = "",
        question_reference: str = "",
        submitted_answer: str = "",
        correct_answer: str = "",
        explanation: str = "",
        source: str = "",
        difficulty: app_commands.Range[int, 1, 5] | None = None,
    ) -> None:
        try:
            result = self.cog.bot.revision_service.add_mistake(
                str(interaction.user.id), subject=subject, chapter=chapter or None,
                topic=topic or None, category=category, question_reference=question_reference or None,
                submitted_answer=submitted_answer or None, correct_answer=correct_answer or None,
                explanation=explanation or None, source=source or None, difficulty=difficulty,
            )
        except RevisionError as exc:
            await reply(interaction, value=embed("Mistake not saved", str(exc), color=ERROR))
            return
        await reply(
            interaction,
            value=embed(
                "📕 Mistake saved",
                f"Revision ID: `{result['revision_item_id'][:8]}`\nFirst review is scheduled for tomorrow.",
                color=SUCCESS,
            ),
        )

    @app_commands.command(name="list", description="Browse your personal mistake book.")
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Scheduled", value="scheduled"),
        app_commands.Choice(name="Reopened", value="reopened"),
        app_commands.Choice(name="Resolved", value="resolved"),
    ])
    async def list_mistakes(self, interaction: discord.Interaction, status: app_commands.Choice[str] | None = None) -> None:
        try:
            selected = status.value if status and status.value != "all" else None
            rows = self.cog.bot.revision_service.mistakes(str(interaction.user.id), status=selected)
        except RevisionError as exc:
            await reply(interaction, value=embed("Mistake book unavailable", str(exc), color=ERROR))
            return
        lines = [
            f"{status_icon(row['status'])} `{row['id'][:8]}` {subject_icon(row['subject'])} **{row['subject']}**"
            + (f" → {row['chapter']}" if row.get("chapter") else "")
            + "\n"
            + f"└ `{row['category']}` • **{row['status'].upper()}** • 🔁 {row['repeat_count']} review(s)"
            for row in rows[:15]
        ]
        await reply(interaction, value=embed("📕 Mistake book", "\n\n".join(lines) or "No mistakes recorded."))


class RevisionGroup(app_commands.Group):
    def __init__(self, cog: "AcademicsCog") -> None:
        super().__init__(name="revision", description="Review due topics and mistakes.")
        self.cog = cog

    @app_commands.command(name="due", description="Show revisions currently due.")
    async def due(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.revision_service.due(str(interaction.user.id))
        if not rows:
            await reply(interaction, value=embed("Revision queue", "Nothing is due right now.", color=SUCCESS))
            return
        lines = [
            f"🔔 `{row['id'][:8]}` • **{row['title']}**\n└ Spacing interval: `{row['interval_days']} day(s)`"
            for row in rows[:15]
        ]
        await reply(interaction, value=embed("🔁 Revisions due", "\n".join(lines)))

    @app_commands.command(name="review", description="Record recall quality and schedule the next revision.")
    @app_commands.choices(result=[
        app_commands.Choice(name="Forgotten", value="forgotten"),
        app_commands.Choice(name="Hard", value="hard"),
        app_commands.Choice(name="Good", value="good"),
        app_commands.Choice(name="Easy", value="easy"),
    ])
    async def review(self, interaction: discord.Interaction, revision_id: str, result: app_commands.Choice[str]) -> None:
        try:
            full_id = self.cog.bot.revision_service.resolve_id(str(interaction.user.id), revision_id)
            saved = self.cog.bot.revision_service.review(str(interaction.user.id), full_id, result.value)
        except RevisionError as exc:
            await reply(interaction, value=embed("Revision not saved", str(exc), color=ERROR))
            return
        await reply(
            interaction,
            value=embed(
                "Revision recorded",
                f"Result: **{saved['result'].title()}**\nNext review in **{saved['next_interval_days']} day(s)**.",
                color=SUCCESS,
            ),
        )


class ResourceGroup(app_commands.Group):
    def __init__(self, cog: "AcademicsCog") -> None:
        super().__init__(name="resource", description="Track books, modules and exact page coverage.")
        self.cog = cog

    @app_commands.command(name="add", description="Add a personal book or module.")
    async def add(
        self,
        interaction: discord.Interaction,
        name: str,
        resource_type: str,
        subject: str = "",
        edition: str = "",
        total_pages: app_commands.Range[int, 1, 100000] | None = None,
    ) -> None:
        try:
            resource = self.cog.bot.coverage_service.add_resource(
                str(interaction.user.id), name=name, resource_type=resource_type,
                subject_code=subject or None, edition=edition or None, total_pages=total_pages,
            )
        except CoverageError as exc:
            await reply(interaction, value=embed("Resource not added", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("📚 Resource added", f"**{resource['name']}**\nID: `{resource['id'][:8]}`", color=SUCCESS))

    @app_commands.command(name="list", description="List your active books and modules.")
    async def list_resources(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.coverage_service.list_resources(str(interaction.user.id))
        if not rows:
            await reply(interaction, value=embed("Resources", "No resources added yet."))
            return
        lines = [
            f"📘 `{row['id'][:8]}` • **{row['name']}**\n"
            f"└ `{row['resource_type'].upper()}` • {subject_icon(row.get('subject_code') or '')} {row.get('subject_code') or 'General'}"
            for row in rows[:20]
        ]
        await reply(interaction, value=embed("📚 Your resources", "\n".join(lines)))

    @app_commands.command(name="pages", description="Record an exact page range without double-counting overlaps.")
    async def pages(
        self,
        interaction: discord.Interaction,
        resource: str,
        page_start: app_commands.Range[int, 1, 100000],
        page_end: app_commands.Range[int, 1, 100000],
        activity: str,
    ) -> None:
        try:
            found = self.cog.bot.coverage_service.find_resource(str(interaction.user.id), resource)
            result = self.cog.bot.coverage_service.record_pages(
                str(interaction.user.id), found["id"], page_start=page_start,
                page_end=page_end, activity=activity,
            )
        except CoverageError as exc:
            await reply(interaction, value=embed("Pages not saved", str(exc), color=ERROR))
            return
        coverage = result["coverage_percent"]
        percentage = "`Unknown total page count`" if coverage is None else progress_bar(coverage, 100, width=12)
        await reply(
            interaction,
            value=embed(
                "Pages recorded",
                f"📘 **{found['name']}**\n"
                f"📄 `{result['covered_pages']} unique pages` • **{activity}**\n"
                f"{percentage}",
                color=SUCCESS,
            ),
        )

    @app_commands.command(name="coverage", description="Show page coverage by activity for one resource.")
    async def coverage(self, interaction: discord.Interaction, resource: str) -> None:
        try:
            found = self.cog.bot.coverage_service.find_resource(str(interaction.user.id), resource)
            rows = self.cog.bot.coverage_service.coverage_summary(str(interaction.user.id), found["id"])
        except CoverageError as exc:
            await reply(interaction, value=embed("Coverage unavailable", str(exc), color=ERROR))
            return
        lines = [
            f"📖 **{row['activity']}** • `{row['covered_pages']} unique pages`\n"
            + (
                f"└ {progress_bar(row['coverage_percent'], 100, width=9)}"
                if row["coverage_percent"] is not None else "└ `Total page count unavailable`"
            )
            for row in rows
        ]
        await reply(interaction, value=embed(f"📖 {found['name']}", "\n".join(lines) or "No pages recorded."))


class AcademicsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.groups = [PracticeGroup(self), MistakeGroup(self), RevisionGroup(self), ResourceGroup(self)]
        for group in self.groups:
            self.bot.tree.add_command(group)

    async def cog_unload(self) -> None:
        for group in self.groups:
            self.bot.tree.remove_command(group.name, type=group.type)

    @app_commands.command(name="progress", description="View today’s real study, practice, revision and mastery summary.")
    async def progress(self, interaction: discord.Interaction) -> None:
        try:
            data = self.bot.analytics_service.today(str(interaction.user.id))
        except ValueError as exc:
            await reply(interaction, value=embed("Progress unavailable", str(exc), color=ERROR))
            return
        mastery = "\n\n".join(
            f"{subject_icon(row['subject'])} **{row['subject']}**\n"
            f"└ {progress_bar(row['score'], 100, width=9)} • `{row['confidence'] * 100:.0f}% confidence`"
            for row in data["mastery"]
        ) or "No mastery evidence yet."
        accuracy = data["question_accuracy"]
        text = (
            f"📅 `{data['local_date']}`  •  `LIVE ACADEMIC SNAPSHOT`\n\n"
            f"⚡ **FOCUS:** `{duration(data['focus_seconds'])}` across `{data['sessions']} sessions`\n"
            f"🎯 **QUESTIONS:** `{data['questions_attempted']}`\n"
            + (
                f"└ Accuracy {progress_bar(accuracy, 100, width=10)}\n"
                if accuracy is not None else "└ `No accuracy evidence yet`\n"
            )
            + f"🔔 **REVISIONS DUE:** `{data['revisions_due']}`\n\n"
            f"💎 **CURRENT MASTERY**\n{mastery}"
        )
        await reply(
            interaction,
            value=embed("📊  Daily Progress Command Center", text),
            ephemeral=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AcademicsCog(bot))
