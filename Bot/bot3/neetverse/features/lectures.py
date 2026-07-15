"""Premium Discord-native YouTube lecture discovery and saving."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.lectures import LectureError
from neetverse.ui import (
    ERROR,
    SUCCESS,
    compact_number,
    duration,
    embed,
    progress_bar,
    reply,
    status_icon,
    subject_icon,
)


def lecture_embed(
    item: dict,
    *,
    index: int,
    total: int,
    subject: str,
    topic: str,
) -> discord.Embed:
    seconds = item.get("duration_seconds")
    length = duration(seconds) if seconds is not None else "Unknown"
    views = compact_number(int(item.get("view_count") or 0))
    published = str(item.get("published_at") or "")[:10] or "Unknown"
    page_bar = progress_bar(index + 1, total, width=10)
    description = (
        f"{page_bar}\n"
        f"`RESULT {index + 1:02d}/{total:02d}`  •  {subject_icon(subject)} **{subject}** → **{topic}**\n\n"
        f"📺 **{item.get('channel_title') or 'Unknown channel'}**\n"
        f"⏱️ `{length}`  •  👁️ `{views} views`  •  📅 `{published}`\n\n"
        f"💎 **WHY THIS MATCHED**\n"
        f"> {item.get('selection_reason') or 'Relevant NEET lecture result'}\n\n"
        "▶️ Use the player below, or press **Watch on YouTube**."
    )
    value = embed(f"🎬  {item.get('title') or 'NEET Lecture'}", description)
    value.url = str(item.get("url") or "") or None
    thumbnail = str(item.get("thumbnail_url") or "").strip()
    if thumbnail:
        value.set_thumbnail(url=thumbnail)
    value.set_footer(text=f"NEETVERSE  •  YOUTUBE LECTURE DECK  •  {index + 1}/{total}")
    return value


class LectureResultsView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        user_id: int,
        results: list[dict],
        subject: str,
        topic: str,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = str(user_id)
        self.results = results
        self.subject = subject
        self.topic = topic
        self.index = 0
        self.message: discord.Message | None = None
        self.saved_video_ids: set[str] = set()
        self.watch_button = discord.ui.Button(
            label="Watch on YouTube",
            emoji="▶️",
            style=discord.ButtonStyle.link,
            url=str(self.current["url"]),
            row=1,
        )
        self.add_item(self.watch_button)
        self._sync_controls()

    async def on_timeout(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button) or item.style != discord.ButtonStyle.link:
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.DiscordException:
                pass

    @property
    def current(self) -> dict:
        return self.results[self.index]

    def current_embed(self) -> discord.Embed:
        return lecture_embed(
            self.current,
            index=self.index,
            total=len(self.results),
            subject=self.subject,
            topic=self.topic,
        )

    def _sync_controls(self) -> None:
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index == len(self.results) - 1
        self.page_indicator.label = f"{self.index + 1}/{len(self.results)}"
        self.watch_button.url = str(self.current["url"])
        is_saved = str(self.current["video_id"]) in self.saved_video_ids
        self.save_lecture.disabled = is_saved
        self.save_lecture.label = "Saved" if is_saved else "Save lecture"
        self.save_lecture.emoji = "✅" if is_saved else "🔖"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="These lecture controls belong to another student. Use `/lecture find` for your own deck.")
            return False
        return True

    async def _show(self, interaction: discord.Interaction) -> None:
        self._sync_controls()
        await interaction.response.edit_message(
            content=f"▶️ **PLAYABLE YOUTUBE LECTURE**\n{self.current['url']}",
            embed=self.current_embed(),
            view=self,
        )

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.primary, row=0)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        pass

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = min(len(self.results) - 1, self.index + 1)
        await self._show(interaction)

    @discord.ui.button(label="Save lecture", emoji="🔖", style=discord.ButtonStyle.success, row=1)
    async def save_lecture(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        lecture = self.current
        try:
            saved = self.bot.lecture_service.save(
                str(interaction.user.id),
                lecture,
                subject=self.subject,
                topic=self.topic,
            )
        except LectureError as exc:
            await reply(interaction, value=embed("Lecture not saved", str(exc), color=ERROR))
            return
        self.saved_video_ids.add(str(lecture["video_id"]))
        self._sync_controls()
        await interaction.response.edit_message(
            content=f"▶️ **PLAYABLE YOUTUBE LECTURE**\n{self.current['url']}",
            embed=self.current_embed(),
            view=self,
        )
        await interaction.followup.send(
            embed=embed(
                "Lecture saved",
                f"🔖 **[{saved['title']}]({saved['url']})**\nAdded to your personal lecture queue.",
                color=SUCCESS,
            ),
            ephemeral=True,
        )


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
        await interaction.response.defer(thinking=True)
        try:
            results = await self.cog.bot.lecture_service.search(
                subject=subject,
                topic=topic,
                language=language,
                lecture_type=lecture_type.value,
                max_results=5,
            )
        except LectureError as exc:
            await interaction.followup.send(
                embed=embed("Lecture search unavailable", str(exc), color=ERROR), ephemeral=True
            )
            return
        if not results:
            await interaction.followup.send(
                embed=embed(
                    "No lectures found",
                    "🔎 Try a broader chapter or topic name, then search again.",
                ),
                ephemeral=True,
            )
            return
        view = LectureResultsView(
            self.cog.bot, interaction.user.id, results, subject, topic
        )
        view.message = await interaction.followup.send(
            content=f"▶️ **PLAYABLE YOUTUBE LECTURE**\n{view.current['url']}",
            embed=view.current_embed(),
            view=view,
            wait=True,
        )

    @app_commands.command(name="saved", description="List lectures saved to your personal study queue.")
    async def saved(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.lecture_service.saved(str(interaction.user.id))
        stage = {"saved": 1, "planned": 2, "watching": 3, "completed": 4}
        lines = [
            f"{status_icon(row['status'])} `{row['id'][:8]}` **[{row['title']}]({row['url']})**\n"
            f"└ {subject_icon(row.get('subject') or '')} {row.get('subject') or 'General'} • "
            f"{progress_bar(stage.get(row['status'], 0), 4, width=6)} • `{row['status'].upper()}`"
            for row in rows[:15]
        ]
        await reply(
            interaction,
            value=embed(
                "🎞️  Saved lecture library",
                "\n\n".join(lines)
                or "📭 Your lecture library is empty. Use `/lecture find` to discover one.",
            ),
        )

    @app_commands.command(name="status", description="Update a saved lecture's study status.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Saved", value="saved"),
        app_commands.Choice(name="Planned", value="planned"),
        app_commands.Choice(name="Watching", value="watching"),
        app_commands.Choice(name="Completed", value="completed"),
        app_commands.Choice(name="Archived", value="archived"),
    ])
    async def status(
        self,
        interaction: discord.Interaction,
        lecture_id: str,
        status: app_commands.Choice[str],
    ) -> None:
        try:
            row = self.cog.bot.lecture_service.update_status(
                str(interaction.user.id), lecture_id, status.value
            )
        except LectureError as exc:
            await reply(interaction, value=embed("Lecture not updated", str(exc), color=ERROR))
            return
        stage = {"saved": 1, "planned": 2, "watching": 3, "completed": 4}
        bar = progress_bar(stage.get(status.value, 0), 4, width=10)
        await reply(
            interaction,
            value=embed(
                "Lecture updated",
                f"{status_icon(status.value)} **{row['title']}**\n{bar}\nStatus → **{status.name}**",
                color=SUCCESS,
            ),
        )


class LectureCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = LectureGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LectureCog(bot))
