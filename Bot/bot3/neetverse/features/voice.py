"""Discord-native AI voice companion powered by Edge TTS."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ai import AIQuotaExceeded, AIUnavailable
from neetverse.speech import SpeechError
from neetverse.ui import ERROR, SUCCESS, embed, progress_bar, reply
from neetverse.voice import VoiceError


class SpeakResponseView(discord.ui.View):
    """Lets the requesting student send an existing AI answer to their VC."""

    def __init__(self, bot: commands.Bot, user_id: int, text: str, *, title: str) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = int(user_id)
        self.text = str(text)
        self.title = str(title)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await reply(interaction, content="Ask NeetVerse your own question to control its voice reply.")
            return False
        return True

    @discord.ui.button(label="Speak in VC", emoji="🔊", style=discord.ButtonStyle.success)
    async def speak(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            position = await self.bot.voice_manager.enqueue(
                guild=interaction.guild,
                member=interaction.user,
                text_channel_id=interaction.channel_id,
                text=self.text,
                title=self.title,
            )
        except VoiceError as exc:
            await interaction.followup.send(embed=embed("Voice unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.followup.send(
            embed=embed("🔊 Added to voice", f"Queue position: **{position}**", color=SUCCESS),
            ephemeral=True,
        )

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_audio(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            removed = self.bot.voice_manager.stop(interaction.guild, interaction.user)
        except VoiceError as exc:
            await reply(interaction, value=embed("Voice unavailable", str(exc), color=ERROR))
            return
        await reply(interaction, value=embed("Voice stopped", f"Cleared **{removed}** queued replies."))


def voice_status_embed(bot: commands.Bot, guild: discord.Guild | None) -> discord.Embed:
    status = bot.voice_manager.status(guild)
    capacity = bot.voice_manager.queue_limit
    queue_bar = progress_bar(status["queued"], capacity, width=10)
    connection_bar = "🟢 ONLINE" if status["connected"] else "⚫ OFFLINE"
    speaking = status["current"] or "Idle"
    requester = f" • requested by {status['requester']}" if status["requester"] else ""
    return embed(
        "🎙️ NeetVerse Voice Companion",
        f"**Connection:** `{connection_bar}`\n"
        f"**Channel:** {status['channel']}\n"
        f"**Speaking:** {speaking}{requester}\n"
        f"**Queue:** {queue_bar} • `{status['queued']}/{capacity}`\n\n"
        "Voice output is text-triggered. NeetVerse is not listening to the voice channel.",
        color=SUCCESS if status["connected"] else 0x6C5CE7,
    )


class VoiceGroup(app_commands.Group):
    def __init__(self, cog: "VoiceCog") -> None:
        super().__init__(name="voice", description="Talk with the NeetVerse AI companion in a voice channel.")
        self.cog = cog

    @app_commands.command(name="join", description="Connect NeetVerse to your current voice channel.")
    async def join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            voice_client = await self.cog.bot.voice_manager.connect(interaction.guild, interaction.user)
        except VoiceError as exc:
            await interaction.followup.send(embed=embed("Voice unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.followup.send(
            embed=embed(
                "🎙️ Voice companion connected",
                f"Ready in {voice_client.channel.mention}. Use `/voice ask` or an AI answer's **Speak in VC** button.",
                color=SUCCESS,
            )
        )

    @app_commands.command(name="ask", description="Ask the academic AI and hear its answer in your voice channel.")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            await self.cog.bot.voice_manager.connect(interaction.guild, interaction.user)
            result = await self.cog.bot.academic_ai.tutor(str(interaction.user.id), question)
            position = await self.cog.bot.voice_manager.enqueue(
                guild=interaction.guild,
                member=interaction.user,
                text_channel_id=interaction.channel_id,
                text=result.content,
                title=question,
            )
        except VoiceError as exc:
            await interaction.followup.send(embed=embed("Voice unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        except (AIUnavailable, AIQuotaExceeded) as exc:
            await interaction.followup.send(embed=embed("AI unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        value = embed("🧠 NeetVerse Voice Tutor", result.content)
        value.add_field(name="Voice queue", value=f"Position **{position}**", inline=True)
        value.set_footer(text=f"NeetVerse • Free model: {result.model_used} • Text-triggered voice")
        await interaction.followup.send(
            embed=value,
            view=SpeakResponseView(
                self.cog.bot, interaction.user.id, result.content, title=question
            ),
        )

    @app_commands.command(name="repeat", description="Repeat the latest voice explanation using your voice settings.")
    async def repeat(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            position = await self.cog.bot.voice_manager.repeat(
                guild=interaction.guild,
                member=interaction.user,
                text_channel_id=interaction.channel_id,
            )
        except VoiceError as exc:
            await interaction.followup.send(embed=embed("Cannot repeat", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.followup.send(
            embed=embed("🔁 Explanation queued", f"Queue position: **{position}**", color=SUCCESS)
        )

    @app_commands.command(name="stop", description="Stop the current explanation and clear the voice queue.")
    async def stop(self, interaction: discord.Interaction) -> None:
        try:
            removed = self.cog.bot.voice_manager.stop(interaction.guild, interaction.user)
        except VoiceError as exc:
            await reply(interaction, value=embed("Cannot stop voice", str(exc), color=ERROR))
            return
        await interaction.response.send_message(
            embed=embed("⏹️ Voice stopped", f"Cleared **{removed}** queued replies.")
        )

    @app_commands.command(name="leave", description="Disconnect NeetVerse from your current voice channel.")
    async def leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            await self.cog.bot.voice_manager.leave(interaction.guild, interaction.user)
        except VoiceError as exc:
            await interaction.followup.send(embed=embed("Cannot leave", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.followup.send(
            embed=embed("👋 Voice companion disconnected", "The queue was cleared.")
        )

    @app_commands.command(name="status", description="Show the current voice channel, speaker, and queue.")
    async def status(self, interaction: discord.Interaction) -> None:
        try:
            value = voice_status_embed(self.cog.bot, interaction.guild)
        except VoiceError as exc:
            await reply(interaction, value=embed("Voice unavailable", str(exc), color=ERROR))
            return
        await interaction.response.send_message(embed=value)

    @app_commands.command(name="settings", description="View or update your independent Edge TTS voice settings.")
    async def settings(
        self,
        interaction: discord.Interaction,
        voice_name: str | None = None,
        rate_percent: app_commands.Range[int, -50, 50] | None = None,
        pitch_hz: app_commands.Range[int, -50, 50] | None = None,
    ) -> None:
        user_id = str(interaction.user.id)
        try:
            if voice_name is not None or rate_percent is not None or pitch_hz is not None:
                self.cog.bot.profile_service.ensure_draft(
                    user_id, interaction.user.display_name
                )
                preferences = self.cog.bot.speech_preferences.update(
                    user_id,
                    voice_name=voice_name,
                    rate_percent=rate_percent,
                    pitch_hz=pitch_hz,
                )
            else:
                preferences = self.cog.bot.speech_preferences.get(user_id)
        except SpeechError as exc:
            await reply(interaction, value=embed("Invalid voice settings", str(exc), color=ERROR))
            return
        await reply(
            interaction,
            value=embed(
                "🎛️ Your voice settings",
                f"**Voice:** `{preferences.voice_name}`\n"
                f"**Rate:** `{preferences.rate}`\n"
                f"**Pitch:** `{preferences.pitch}`\n\n"
                "Use `voice_name: default` to restore the server default. Find exact names with `/voice voices`.",
                color=SUCCESS,
            ),
        )

    @app_commands.command(name="voices", description="Find Edge TTS voices by language, locale, name, or gender.")
    async def voices(self, interaction: discord.Interaction, search: str = "") -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            voices = await self.cog.bot.speech_service.voices(search)
        except SpeechError as exc:
            await interaction.followup.send(embed=embed("Voice list unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        if not voices:
            await interaction.followup.send(
                embed=embed("No voices found", "Try a locale such as `en-IN`, `hi-IN`, or a broader search."),
                ephemeral=True,
            )
            return
        lines = [
            f"`{voice.get('ShortName', 'Unknown')}` • {voice.get('Gender', 'Unknown')}"
            for voice in voices
        ]
        await interaction.followup.send(
            embed=embed("🗣️ Edge TTS voices", "\n".join(lines)), ephemeral=True
        )


class VoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = VoiceGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCog(bot))
