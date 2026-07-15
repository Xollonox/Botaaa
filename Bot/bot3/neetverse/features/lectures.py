"""Discord-native YouTube lecture discovery and saving."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.lectures import LectureError
from neetverse.ui import ERROR, SUCCESS, duration, embed, reply


class LectureSaveSelect(discord.ui.Select):
    def __init__(self, view: "LectureResultsView") -> None:
        options = [
            discord.SelectOption(
                label=str(item["title"])[:100],
                description=f"{item['channel_title']} • {duration(item.get('duration_seconds') or 0)}"[:100],
                value=str(item["video_id"]),
            )
            for item in view.results[:25]
        ]
        super().__init__(placeholder="Save a lecture…", options=options)
        self.results_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        video_id = self.values[0]
        lecture = next((item for item in self.results_view.results if item["video_id"] == video_id), None)
        if lecture is None:
            await reply(interaction, value=embed("Lecture unavailable", "This result is no longer available.", color=ERROR))
            return
        saved = self.results_view.bot.lecture_service.save(
            str(interaction.user.id), lecture,
            subject=self.results_view.subject, topic=self.results_view.topic,
        )
        await reply(interaction, value=embed("Lecture saved", f"[{saved['title']}]({saved['url']})", color=SUCCESS))


class LectureResultsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int, results: list[dict], subject: str, topic: str) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = str(user_id)
        self.results = results
        self.subject = subject
        self.topic = topic
        self.add_item(LectureSaveSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="These lecture results belong to another student.")
            return False
        return True


class LectureGroup(app_commands.Group):
    def __init__(self, cog: "LectureCog") -> None:
        super().__init__(name="lecture", description="Find NEET lectures without leaving Discord.")
        self.cog = cog

    @app_commands.command(name="find", description="Search YouTube for a relevant NEET lecture.")
    @app_commands.choices(lecture_type=[
        app_commands.Choice(name="Detailed lecture", value="detailed"),
        app_commands.Choice(name="Revision / one shot", value="revision"),
    ])
    async def find(
        self,
        interaction: discord.Interaction,
        subject: str,
        topic: str,
        lecture_type: app_commands.Choice[str],
        language: str = "",
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            results = await self.cog.bot.lecture_service.search(
                subject=subject, topic=topic, language=language,
                lecture_type=lecture_type.value, max_results=5,
            )
        except LectureError as exc:
            await interaction.followup.send(embed=embed("Lecture search unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        if not results:
            await interaction.followup.send(embed=embed("No lectures found", "Try a broader topic name."), ephemeral=True)
            return
        lines = []
        for index, item in enumerate(results, 1):
            length = duration(item.get("duration_seconds") or 0) if item.get("duration_seconds") is not None else "Unknown duration"
            lines.append(
                f"**{index}. [{item['title']}]({item['url']})**\n"
                f"{item['channel_title']} • {length} • {item['view_count']:,} views\n"
                f"_{item['selection_reason']}_"
            )
        await interaction.followup.send(
            embed=embed(f"🎥 {subject} • {topic}", "\n\n".join(lines)),
            view=LectureResultsView(self.cog.bot, interaction.user.id, results, subject, topic),
            ephemeral=True,
        )

    @app_commands.command(name="saved", description="List lectures saved to your personal study queue.")
    async def saved(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.lecture_service.saved(str(interaction.user.id))
        lines = [
            f"`{row['id'][:8]}` **[{row['title']}]({row['url']})**\n{row.get('subject') or 'General'} • {row['status']}"
            for row in rows
        ]
        await reply(interaction, value=embed("🎥 Saved lectures", "\n\n".join(lines) or "No saved lectures."))

    @app_commands.command(name="status", description="Update a saved lecture's study status.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Saved", value="saved"),
        app_commands.Choice(name="Planned", value="planned"),
        app_commands.Choice(name="Watching", value="watching"),
        app_commands.Choice(name="Completed", value="completed"),
        app_commands.Choice(name="Archived", value="archived"),
    ])
    async def status(self, interaction: discord.Interaction, lecture_id: str, status: app_commands.Choice[str]) -> None:
        try:
            row = self.cog.bot.lecture_service.update_status(str(interaction.user.id), lecture_id, status.value)
        except LectureError as exc:
            await reply(interaction, value=embed("Lecture not updated", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Lecture updated", f"**{row['title']}** is now **{status.name}**.", color=SUCCESS))


class LectureCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = LectureGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LectureCog(bot))
