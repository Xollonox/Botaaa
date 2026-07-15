"""Persistent reminder delivery and user notification settings."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import MISSING

from neetverse.profiles import ProfileValidationError
from neetverse.ui import ERROR, SUCCESS, embed, reply


logger = logging.getLogger(__name__)


class ReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        # discord.py creates the ready event during its asynchronous client
        # setup. Keeping this guard also allows offline command-tree tests to
        # load the extension without spawning an unusable background task.
        if getattr(self.bot, "_ready", MISSING) is not MISSING:
            self.deliver_due.start()

    def cog_unload(self) -> None:
        self.deliver_due.cancel()

    @app_commands.command(name="reminders", description="Configure private DM reminders and optional quiet hours.")
    async def reminders(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        quiet_start: str = "",
        quiet_end: str = "",
    ) -> None:
        profile = self.bot.profile_service.get(str(interaction.user.id))
        if profile is None:
            await reply(interaction, value=embed("No profile", "Run `/start` first.", color=ERROR))
            return
        if bool(quiet_start) != bool(quiet_end):
            await reply(interaction, value=embed("Settings not saved", "Provide both quiet-hour times or neither.", color=ERROR))
            return
        try:
            updated = self.bot.profile_service.update(
                str(interaction.user.id),
                {
                    "dm_reminders": enabled,
                    "quiet_hours_start": quiet_start or None,
                    "quiet_hours_end": quiet_end or None,
                },
            )
        except ProfileValidationError as exc:
            await reply(interaction, value=embed("Settings not saved", str(exc), color=ERROR))
            return
        quiet = (
            f" Quiet hours: **{updated['quiet_hours_start']}–{updated['quiet_hours_end']}**."
            if updated.get("quiet_hours_start") else ""
        )
        await reply(
            interaction,
            value=embed(
                "Reminder settings",
                f"Private DM reminders are **{'enabled' if enabled else 'disabled'}**.{quiet}",
                color=SUCCESS,
            ),
        )

    @tasks.loop(seconds=30)
    async def deliver_due(self) -> None:
        for job in self.bot.reminder_service.claim_due(limit=20):
            try:
                user = self.bot.get_user(int(job["user_id"])) or await self.bot.fetch_user(int(job["user_id"]))
                await user.send(embed=_job_embed(job))
            except Exception as exc:
                logger.warning("Reminder delivery failed job=%s user=%s error=%s", job["id"], job["user_id"], exc)
                self.bot.reminder_service.failed(job["id"], str(exc))
            else:
                self.bot.reminder_service.delivered(job["id"])

    @deliver_due.before_loop
    async def before_delivery(self) -> None:
        await self.bot.wait_until_ready()


def _job_embed(job: dict) -> discord.Embed:
    payload = job.get("payload", {})
    if job["job_type"] == "revision_due":
        return embed("🔁 Revision due", f"**{payload.get('title', 'A revision item')}** is ready.\nUse `/revision due` to review it.")
    if job["job_type"] == "pomodoro_phase":
        phase = str(payload.get("phase", "focus")).replace("_", " ").title()
        return embed("⏱️ Pomodoro phase complete", f"Your **{phase}** target has elapsed.\nUse `/study next_phase` when ready.")
    if job["job_type"] == "countdown_target":
        return embed("⏱️ Study target reached", f"Your countdown for **{payload.get('subject', 'study')}** has elapsed.\nUse `/study finish` or continue intentionally.")
    if job["job_type"] == "goal_due":
        return embed("🎯 Goal due", f"**{payload.get('title', 'A study goal')}** is due today.\nUse `/goal list` to review it.")
    return embed("NeetVerse reminder", str(payload.get("message", "You have a scheduled study reminder.")))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReminderCog(bot))
