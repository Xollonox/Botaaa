from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from neetverse.speech import EdgeSpeechService, SpeechPreferenceService, SpeechPreferences
from neetverse.voice import VoiceError, VoiceSessionManager


def _voice_environment():
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 44
    channel.mention = "<#44>"
    channel.permissions_for.return_value = SimpleNamespace(connect=True, speak=True)

    member = MagicMock(spec=discord.Member)
    member.id = 7
    member.display_name = "Student"
    member.voice = SimpleNamespace(channel=channel)

    voice_client = MagicMock(spec=discord.VoiceClient)
    voice_client.channel = channel
    voice_client.is_connected.return_value = True
    voice_client.is_playing.return_value = False
    voice_client.is_paused.return_value = False
    voice_client.disconnect = AsyncMock()
    voice_client.play.side_effect = lambda source, *, after: after(None)

    guild = MagicMock(spec=discord.Guild)
    guild.id = 11
    guild.me = MagicMock(spec=discord.Member)
    guild.voice_client = voice_client

    bot = MagicMock(spec=commands.Bot)
    bot.get_guild.return_value = guild
    bot.get_channel.return_value = None
    bot.voice_clients = []

    speech = MagicMock(spec=EdgeSpeechService)
    speech.render = AsyncMock(return_value=MagicMock())
    speech.cleanup = MagicMock()
    preferences = MagicMock(spec=SpeechPreferenceService)
    preferences.get.return_value = SpeechPreferences("en-IN-NeerjaNeural", 0, 0)
    manager = VoiceSessionManager(
        bot, speech, preferences, queue_limit=2, idle_seconds=30
    )
    return manager, bot, guild, member, voice_client, speech


def test_voice_queue_serializes_playback_and_keeps_repeatable_answer(monkeypatch) -> None:
    async def scenario() -> None:
        manager, _, guild, member, voice_client, speech = _voice_environment()
        monkeypatch.setattr(discord, "FFmpegPCMAudio", MagicMock(return_value=MagicMock()))

        position = await manager.enqueue(
            guild=guild,
            member=member,
            text_channel_id=99,
            text="Read NCERT and solve ten questions.",
            title="What should I study?",
        )
        assert position == 1
        state = manager._states[guild.id]
        await asyncio.wait_for(state.queue.join(), timeout=2)

        assert voice_client.play.call_count == 1
        assert state.last is not None
        assert state.last.requester_id == member.id
        assert manager.status(guild)["queued"] == 0
        speech.cleanup.assert_called()
        await manager.close()

    asyncio.run(scenario())


def test_voice_control_requires_member_in_the_active_channel() -> None:
    manager, _, guild, member, _, _ = _voice_environment()
    other_channel = MagicMock(spec=discord.VoiceChannel)
    other_channel.id = 55
    member.voice = SimpleNamespace(channel=other_channel)

    with pytest.raises(VoiceError, match="current voice channel"):
        manager.stop(guild, member)
