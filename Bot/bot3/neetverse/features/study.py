"""Discord controls for persistent study sessions."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.study import StudyError, StudyService
from neetverse.ui import ERROR, SUCCESS, duration, embed, reply


def session_embed(session: dict) -> discord.Embed:
    status = str(session["status"]).replace("_", " ").title()
    phase = str(session["phase"]).replace("_", " ").title()
    lines = [
        f"**{session['subject']}** • {session['activity']}",
        f"Status: **{status}**",
        f"Focus: **{duration(session['focus_seconds'])}**",
        f"Paused: {duration(session['paused_seconds'])}",
        f"Breaks: {duration(session['break_seconds'])}",
    ]
    if session.get("chapter"):
        lines.insert(1, f"Chapter: {session['chapter']}")
    if session["mode"] == "pomodoro":
        lines.extend(
            [
                f"Phase: **{phase}**",
                f"Phase remaining: **{duration(session.get('phase_remaining_seconds', 0))}**",
                f"Focus cycles completed: **{session['pomodoro_cycles_completed']}**",
            ]
        )
    elif session.get("remaining_seconds") is not None:
        lines.append(f"Target remaining: **{duration(session['remaining_seconds'])}**")
    color = SUCCESS if session["status"] == "completed" else 0x6C5CE7
    if session["status"] == "review_required":
        color = 0xF1C40F
        lines.append("⚠️ This unusually long session needs review before competitive credit.")
    return embed("⏱️ Study Session", "\n".join(lines), color=color)


class StudyControlView(discord.ui.View):
    def __init__(self, service: StudyService, user_id: int) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.user_id = str(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="This study panel belongs to another student.")
            return False
        return True

    async def refresh(self, interaction: discord.Interaction, action) -> None:
        try:
            session = action()
        except StudyError as exc:
            await reply(interaction, value=embed("Study action unavailable", str(exc), color=ERROR))
            return
        await interaction.response.edit_message(embed=session_embed(session), view=self)

    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.refresh(interaction, lambda: self.service.pause(self.user_id))

    @discord.ui.button(label="Resume", emoji="▶️", style=discord.ButtonStyle.success)
    async def resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.refresh(interaction, lambda: self.service.resume(self.user_id))

    @discord.ui.button(label="Break", emoji="☕", style=discord.ButtonStyle.primary)
    async def break_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.refresh(interaction, lambda: self.service.start_break(self.user_id))

    @discord.ui.button(label="Next phase", emoji="⏭️", style=discord.ButtonStyle.primary)
    async def next_phase(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.refresh(interaction, lambda: self.service.advance_pomodoro(self.user_id))

    @discord.ui.button(label="Finish", emoji="✅", style=discord.ButtonStyle.danger)
    async def finish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            session = self.service.finish(self.user_id)
        except StudyError as exc:
            await reply(interaction, value=embed("Study action unavailable", str(exc), color=ERROR))
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(embed=session_embed(session), view=self)
        self.stop()


class StudyGroup(app_commands.Group):
    def __init__(self, cog: "StudyCog") -> None:
        super().__init__(name="study", description="Track focused NEET preparation.")
        self.cog = cog

    @app_commands.command(name="start", description="Start a stopwatch, countdown, or Pomodoro study session.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Stopwatch", value="stopwatch"),
            app_commands.Choice(name="Countdown", value="countdown"),
            app_commands.Choice(name="Pomodoro", value="pomodoro"),
        ]
    )
    async def start(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        subject: str,
        activity: str,
        chapter: str = "",
        topic: str = "",
        planned_minutes: app_commands.Range[int, 1, 720] | None = None,
    ) -> None:
        user_id = str(interaction.user.id)
        pomodoro = None
        if mode.value == "pomodoro":
            profile = self.cog.bot.profile_service.get(user_id)
            if profile:
                pomodoro = {
                    "focus_minutes": profile.get("pomodoro_focus_minutes"),
                    "short_break_minutes": profile.get("pomodoro_short_break_minutes"),
                    "long_break_minutes": profile.get("pomodoro_long_break_minutes"),
                    "cycles": profile.get("pomodoro_cycles"),
                }
        try:
            session = self.cog.bot.study_service.start(
                user_id,
                mode=mode.value,
                subject=subject,
                activity=activity,
                chapter=chapter,
                topic=topic,
                planned_minutes=planned_minutes,
                pomodoro=pomodoro,
            )
        except StudyError as exc:
            await reply(interaction, value=embed("Session not started", str(exc), color=ERROR))
            return
        await interaction.response.send_message(
            embed=session_embed(session),
            view=StudyControlView(self.cog.bot.study_service, interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="status", description="Show your active study session and controls.")
    async def status(self, interaction: discord.Interaction) -> None:
        session = self.cog.bot.study_service.active_for_user(str(interaction.user.id))
        if session is None:
            await reply(interaction, value=embed("No active session", "Start one with `/study start`.", color=ERROR))
            return
        await interaction.response.send_message(
            embed=session_embed(session),
            view=StudyControlView(self.cog.bot.study_service, interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="log", description="Log focused study completed away from Discord.")
    async def log(
        self,
        interaction: discord.Interaction,
        subject: str,
        activity: str,
        focus_minutes: app_commands.Range[int, 1, 720],
        chapter: str = "",
        topic: str = "",
        notes: str = "",
    ) -> None:
        try:
            session = self.cog.bot.study_service.log_manual(
                str(interaction.user.id), subject=subject, activity=activity,
                focus_minutes=int(focus_minutes), chapter=chapter, topic=topic, notes=notes,
            )
        except StudyError as exc:
            await reply(interaction, value=embed("Study not logged", str(exc), color=ERROR))
            return
        await reply(interaction, value=session_embed(session))

    @app_commands.command(name="history", description="Show your recent completed and reviewed study sessions.")
    async def history(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.study_service.history(str(interaction.user.id))
        lines = []
        for row in rows:
            ended = f"<t:{row['ended_at']}:d>" if row.get("ended_at") else "Unknown date"
            lines.append(
                f"**{row['subject']}** • {row['activity']}\n"
                f"{ended} • {duration(row['focus_seconds'])} focus • {row['mode']} • {row['status']}"
            )
        await reply(interaction, value=embed("⏱️ Study history", "\n\n".join(lines) or "No finished sessions."))

    @app_commands.command(name="pause", description="Pause your active study session.")
    async def pause(self, interaction: discord.Interaction) -> None:
        await self._simple(interaction, self.cog.bot.study_service.pause)

    @app_commands.command(name="resume", description="Resume your paused study session.")
    async def resume(self, interaction: discord.Interaction) -> None:
        await self._simple(interaction, self.cog.bot.study_service.resume)

    @app_commands.command(name="break", description="Start a break during active focus.")
    async def start_break(self, interaction: discord.Interaction) -> None:
        await self._simple(interaction, self.cog.bot.study_service.start_break)

    @app_commands.command(name="next_phase", description="Move a Pomodoro to its next focus or break phase.")
    async def next_phase(self, interaction: discord.Interaction) -> None:
        await self._simple(interaction, self.cog.bot.study_service.advance_pomodoro)

    @app_commands.command(name="finish", description="Complete and save your active study session.")
    async def finish(self, interaction: discord.Interaction, notes: str = "") -> None:
        try:
            session = self.cog.bot.study_service.finish(str(interaction.user.id), notes=notes)
        except StudyError as exc:
            await reply(interaction, value=embed("Session not finished", str(exc), color=ERROR))
            return
        await reply(interaction, value=session_embed(session))

    async def _simple(self, interaction: discord.Interaction, action) -> None:
        try:
            session = action(str(interaction.user.id))
        except StudyError as exc:
            await reply(interaction, value=embed("Study action unavailable", str(exc), color=ERROR))
            return
        await reply(interaction, value=session_embed(session), view=StudyControlView(self.cog.bot.study_service, interaction.user.id))


class StudyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = StudyGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StudyCog(bot))
