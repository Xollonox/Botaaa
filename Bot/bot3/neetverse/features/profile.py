"""Onboarding and editable student profile Discord flows."""

from __future__ import annotations

import json

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.guide import GUIDE_PAGES
from neetverse.profiles import ProfileService, ProfileValidationError
from neetverse.ui import ERROR, SUCCESS, embed, reply


def _hours_to_minutes(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    value = float(text)
    if not 0 <= value <= 24:
        raise ValueError("Availability must be between 0 and 24 hours")
    return int(round(value * 60))


def _optional_float(raw: str) -> float | None:
    return float(raw.strip()) if raw.strip() else None


class BasicsModal(discord.ui.Modal, title="NeetVerse • Academic Profile"):
    target_year = discord.ui.TextInput(label="Target year", placeholder="Example: 2027", max_length=4)
    current_status = discord.ui.TextInput(label="Current class/status", placeholder="Class 11, Class 12, Dropper, Other", max_length=100)
    coaching = discord.ui.TextInput(label="Coaching/school", placeholder="Self-study, school, coaching, hybrid, custom", required=False, max_length=150)
    timezone = discord.ui.TextInput(label="Time zone", placeholder="Example: Asia/Kolkata", max_length=80)
    language = discord.ui.TextInput(label="Preferred language", placeholder="English, Hindi, Hinglish, custom", required=False, max_length=80)

    def __init__(self, service: ProfileService, user_id: str, current: dict) -> None:
        super().__init__()
        self.service = service
        self.user_id = user_id
        self.target_year.default = str(current.get("target_year") or "")
        self.current_status.default = str(current.get("current_status") or "")
        self.coaching.default = str(current.get("coaching") or "")
        self.timezone.default = str(current.get("timezone") or "")
        self.language.default = str(current.get("preferred_language") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            profile = self.service.update(
                self.user_id,
                {
                    "target_year": str(self.target_year),
                    "current_status": str(self.current_status),
                    "coaching": str(self.coaching),
                    "timezone": str(self.timezone),
                    "preferred_language": str(self.language),
                },
            )
        except (ProfileValidationError, ValueError) as exc:
            await reply(interaction, value=embed("Profile not saved", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Profile saved", f"Onboarding status: **{profile['onboarding_status']}**", color=SUCCESS))


class ScheduleModal(discord.ui.Modal, title="NeetVerse • Schedule and Goals"):
    weekday_hours = discord.ui.TextInput(label="Typical weekday hours", placeholder="Example: 5.5", required=False, max_length=5)
    weekend_hours = discord.ui.TextInput(label="Typical weekend hours", placeholder="Example: 8", required=False, max_length=5)
    current_mock = discord.ui.TextInput(label="Current mock score /720", required=False, max_length=6)
    target_score = discord.ui.TextInput(label="Target score /720", required=False, max_length=6)
    problems = discord.ui.TextInput(label="Biggest preparation problems", style=discord.TextStyle.paragraph, required=False, max_length=600)

    def __init__(self, service: ProfileService, user_id: str, current: dict) -> None:
        super().__init__()
        self.service = service
        self.user_id = user_id
        weekday = current.get("weekday_available_minutes")
        weekend = current.get("weekend_available_minutes")
        self.weekday_hours.default = str(round(weekday / 60, 2)) if weekday is not None else ""
        self.weekend_hours.default = str(round(weekend / 60, 2)) if weekend is not None else ""
        self.current_mock.default = str(current.get("current_mock_score") or "")
        self.target_score.default = str(current.get("target_score") or "")
        self.problems.default = ", ".join(current.get("preparation_problems", []))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            problems = [part.strip() for part in str(self.problems).split(",") if part.strip()]
            self.service.update(
                self.user_id,
                {
                    "weekday_available_minutes": _hours_to_minutes(str(self.weekday_hours)),
                    "weekend_available_minutes": _hours_to_minutes(str(self.weekend_hours)),
                    "current_mock_score": _optional_float(str(self.current_mock)),
                    "target_score": _optional_float(str(self.target_score)),
                    "preparation_problems_json": json.dumps(problems, ensure_ascii=False),
                },
            )
        except (ProfileValidationError, ValueError) as exc:
            await reply(interaction, value=embed("Schedule not saved", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Schedule saved", "Your planner will use these constraints.", color=SUCCESS))


class PomodoroModal(discord.ui.Modal, title="NeetVerse • Pomodoro Preferences"):
    focus = discord.ui.TextInput(label="Focus minutes", placeholder="Example: 50", max_length=3)
    short_break = discord.ui.TextInput(label="Short break minutes", placeholder="Example: 10", max_length=3)
    long_break = discord.ui.TextInput(label="Long break minutes", placeholder="Example: 20", max_length=3)
    cycles = discord.ui.TextInput(label="Cycles before long break", placeholder="Example: 4", max_length=2)
    resources = discord.ui.TextInput(label="Main books/modules", style=discord.TextStyle.paragraph, required=False, max_length=600)

    def __init__(self, service: ProfileService, user_id: str, current: dict) -> None:
        super().__init__()
        self.service = service
        self.user_id = user_id
        self.focus.default = str(current.get("pomodoro_focus_minutes") or "")
        self.short_break.default = str(current.get("pomodoro_short_break_minutes") or "")
        self.long_break.default = str(current.get("pomodoro_long_break_minutes") or "")
        self.cycles.default = str(current.get("pomodoro_cycles") or "")
        self.resources.default = ", ".join(current.get("resources", []))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            resources = [part.strip() for part in str(self.resources).split(",") if part.strip()]
            self.service.update(
                self.user_id,
                {
                    "pomodoro_focus_minutes": str(self.focus),
                    "pomodoro_short_break_minutes": str(self.short_break),
                    "pomodoro_long_break_minutes": str(self.long_break),
                    "pomodoro_cycles": str(self.cycles),
                    "resources_json": json.dumps(resources, ensure_ascii=False),
                },
            )
        except (ProfileValidationError, ValueError) as exc:
            await reply(interaction, value=embed("Preferences not saved", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Pomodoro saved", "Future Pomodoro sessions will use these values.", color=SUCCESS))


class ProgressModal(discord.ui.Modal, title="NeetVerse • Current Progress"):
    physics = discord.ui.TextInput(label="Physics progress %", required=False, max_length=6)
    chemistry = discord.ui.TextInput(label="Chemistry progress %", required=False, max_length=6)
    biology = discord.ui.TextInput(label="Biology progress %", required=False, max_length=6)

    def __init__(self, service: ProfileService, user_id: str, current: dict) -> None:
        super().__init__()
        self.service = service
        self.user_id = user_id
        progress = current.get("subject_progress", {})
        self.physics.default = str(progress.get("physics", {}).get("progress_percent") or "")
        self.chemistry.default = str(progress.get("chemistry", {}).get("progress_percent") or "")
        self.biology.default = str(progress.get("biology", {}).get("progress_percent") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            for subject, raw in (("physics", str(self.physics)), ("chemistry", str(self.chemistry)), ("biology", str(self.biology))):
                value = float(raw) if raw.strip() else None
                self.service.set_subject_progress(self.user_id, subject, progress_note=None, progress_percent=value)
        except (ProfileValidationError, ValueError) as exc:
            await reply(interaction, value=embed("Progress not saved", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Progress saved", "This is your editable starting estimate, not calculated mastery.", color=SUCCESS))


class ProfileSetupView(discord.ui.View):
    def __init__(self, service: ProfileService, user_id: int) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.user_id = str(user_id)
        self.page = 0
        self.page_total = len(GUIDE_PAGES) + 1
        self._sync_navigation()

    def _sync_navigation(self) -> None:
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == self.page_total - 1
        self.page_indicator.label = f"{self.page + 1}/{self.page_total}"

    def current_embed(self) -> discord.Embed:
        if self.page == 0:
            return profile_embed(self.service.get(self.user_id) or {})
        title, description = GUIDE_PAGES[self.page - 1]
        return embed(title, description)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="This profile panel belongs to another student.")
            return False
        return True

    @discord.ui.button(label="Academic profile", emoji="🎯", style=discord.ButtonStyle.primary, row=0)
    async def basics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BasicsModal(self.service, self.user_id, self.service.get(self.user_id) or {}))

    @discord.ui.button(label="Schedule & goals", emoji="🗓️", style=discord.ButtonStyle.secondary, row=0)
    async def schedule(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ScheduleModal(self.service, self.user_id, self.service.get(self.user_id) or {}))

    @discord.ui.button(label="Pomodoro & books", emoji="⏱️", style=discord.ButtonStyle.secondary, row=0)
    async def pomodoro(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(PomodoroModal(self.service, self.user_id, self.service.get(self.user_id) or {}))

    @discord.ui.button(label="Current progress", emoji="📚", style=discord.ButtonStyle.secondary, row=0)
    async def progress(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ProgressModal(self.service, self.user_id, self.service.get(self.user_id) or {}))

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.primary, row=1)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._sync_navigation()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="1/9", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def page_indicator(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        pass

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.primary, row=1)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = min(self.page_total - 1, self.page + 1)
        self._sync_navigation()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


def profile_embed(profile: dict) -> discord.Embed:
    progress = profile.get("subject_progress", {})
    def percent(subject: str) -> str:
        value = progress.get(subject, {}).get("progress_percent")
        return "Not provided" if value is None else f"{value:g}%"
    weekday = profile.get("weekday_available_minutes")
    weekend = profile.get("weekend_available_minutes")
    resources = ", ".join(profile.get("resources", [])) or "Not provided"
    problems = ", ".join(profile.get("preparation_problems", [])) or "Not provided"
    pomodoro_values = (
        profile.get("pomodoro_focus_minutes"), profile.get("pomodoro_short_break_minutes"),
        profile.get("pomodoro_long_break_minutes"), profile.get("pomodoro_cycles"),
    )
    pomodoro = (
        f"{pomodoro_values[0]}/{pomodoro_values[1]}/{pomodoro_values[2]} min • {pomodoro_values[3]} cycles"
        if all(value is not None for value in pomodoro_values) else "Not configured"
    )
    body = (
        f"**Status:** {profile.get('onboarding_status', 'draft').title()}\n"
        f"**Target:** NEET {profile.get('target_year') or 'Not provided'}\n"
        f"**Class/status:** {profile.get('current_status') or 'Not provided'}\n"
        f"**Coaching:** {profile.get('coaching') or 'Not provided'}\n"
        f"**Time zone:** {profile.get('timezone') or 'Not provided'}\n\n"
        f"**Language:** {profile.get('preferred_language') or 'Not provided'}\n"
        f"**Weekday availability:** {f'{weekday / 60:g}h' if weekday is not None else 'Not provided'}\n"
        f"**Weekend availability:** {f'{weekend / 60:g}h' if weekend is not None else 'Not provided'}\n"
        f"**Mock:** {profile.get('current_mock_score') if profile.get('current_mock_score') is not None else 'Not provided'} / 720\n"
        f"**Target score:** {profile.get('target_score') if profile.get('target_score') is not None else 'Not provided'} / 720\n\n"
        f"**Physics:** {percent('physics')}  •  **Chemistry:** {percent('chemistry')}  •  **Biology:** {percent('biology')}\n\n"
        f"**Pomodoro:** {pomodoro}\n"
        f"**Books/modules:** {resources[:500]}\n"
        f"**Main problems:** {problems[:500]}"
    )
    return embed(f"🎓 {profile.get('display_name', 'Student')}", body)


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="start", description="Create or continue your independent NeetVerse profile.")
    async def start(self, interaction: discord.Interaction) -> None:
        profile = self.bot.profile_service.ensure_draft(str(interaction.user.id), interaction.user.display_name)
        view = ProfileSetupView(self.bot.profile_service, interaction.user.id)
        await interaction.response.send_message(embed=profile_embed(profile), view=view, ephemeral=True)

    @app_commands.command(name="profile", description="View and edit your NeetVerse academic profile.")
    async def profile(self, interaction: discord.Interaction) -> None:
        profile = self.bot.profile_service.get(str(interaction.user.id))
        if profile is None:
            await reply(interaction, value=embed("No profile", "Run `/start` to begin onboarding.", color=ERROR))
            return
        await interaction.response.send_message(
            embed=profile_embed(profile),
            view=ProfileSetupView(self.bot.profile_service, interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
