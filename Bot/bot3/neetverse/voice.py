"""Per-guild Discord voice connections and bounded speech playback queues."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import Any

import discord
from discord.ext import commands

from .speech import EdgeSpeechService, SpeechError, SpeechPreferenceService, SpeechPreferences


logger = logging.getLogger(__name__)


class VoiceError(RuntimeError):
    """A user-safe Discord voice failure."""


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    title: str
    requester_id: int
    requester_name: str
    text_channel_id: int
    preferences: SpeechPreferences


@dataclass
class GuildVoiceState:
    queue: asyncio.Queue[VoiceRequest]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    worker: asyncio.Task[None] | None = None
    current: VoiceRequest | None = None
    last: VoiceRequest | None = None


class VoiceSessionManager:
    """Owns exactly one serialized TTS queue per Discord guild."""

    def __init__(
        self,
        bot: commands.Bot,
        speech: EdgeSpeechService,
        preferences: SpeechPreferenceService,
        *,
        queue_limit: int,
        idle_seconds: int,
    ) -> None:
        self.bot = bot
        self.speech = speech
        self.preferences = preferences
        self.queue_limit = max(1, int(queue_limit))
        self.idle_seconds = max(30, int(idle_seconds))
        self._states: dict[int, GuildVoiceState] = {}

    def _state(self, guild_id: int) -> GuildVoiceState:
        state = self._states.get(int(guild_id))
        if state is None:
            state = GuildVoiceState(asyncio.Queue(maxsize=self.queue_limit))
            self._states[int(guild_id)] = state
        return state

    async def connect(self, guild: discord.Guild | None, member: discord.Member | discord.User) -> discord.VoiceClient:
        destination = self._destination(guild, member)
        assert guild is not None
        state = self._state(guild.id)
        async with state.lock:
            voice_client = await self._connect_locked(guild, destination)
            self._ensure_worker(guild.id, state)
            return voice_client

    async def enqueue(
        self,
        *,
        guild: discord.Guild | None,
        member: discord.Member | discord.User,
        text_channel_id: int,
        text: str,
        title: str,
    ) -> int:
        if not str(text).strip():
            raise VoiceError("There is no answer to speak.")
        destination = self._destination(guild, member)
        assert guild is not None
        state = self._state(guild.id)
        async with state.lock:
            await self._connect_locked(guild, destination)
            if state.queue.full():
                raise VoiceError("The voice queue is full. Wait for the current explanations to finish.")
            request = VoiceRequest(
                text=str(text),
                title=str(title)[:100],
                requester_id=int(member.id),
                requester_name=str(getattr(member, "display_name", member)),
                text_channel_id=int(text_channel_id),
                preferences=self.preferences.get(str(member.id)),
            )
            state.queue.put_nowait(request)
            position = state.queue.qsize() + (1 if state.current else 0)
            self._ensure_worker(guild.id, state)
            return position

    async def repeat(
        self,
        *,
        guild: discord.Guild | None,
        member: discord.Member | discord.User,
        text_channel_id: int,
    ) -> int:
        if guild is None:
            raise VoiceError("Voice replies can only be used inside a Discord server.")
        destination = self._destination(guild, member)
        state = self._state(guild.id)
        async with state.lock:
            previous = state.last or state.current
            if previous is None:
                raise VoiceError("Nothing has been spoken in this server yet.")
            await self._connect_locked(guild, destination)
            if state.queue.full():
                raise VoiceError("The voice queue is full.")
            request = replace(
                previous,
                requester_id=int(member.id),
                requester_name=str(getattr(member, "display_name", member)),
                text_channel_id=int(text_channel_id),
                preferences=self.preferences.get(str(member.id)),
            )
            state.queue.put_nowait(request)
            position = state.queue.qsize() + (1 if state.current else 0)
            self._ensure_worker(guild.id, state)
            return position

    def stop(self, guild: discord.Guild | None, member: discord.Member | discord.User) -> int:
        voice_client, state = self._controlled_state(guild, member)
        removed = 0
        while not state.queue.empty():
            try:
                state.queue.get_nowait()
                state.queue.task_done()
                removed += 1
            except asyncio.QueueEmpty:
                break
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        return removed

    async def leave(self, guild: discord.Guild | None, member: discord.Member | discord.User) -> None:
        voice_client, state = self._controlled_state(guild, member)
        worker = state.worker
        if worker is not None and not worker.done():
            worker.cancel()
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        await voice_client.disconnect(force=True)
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)
        self._states.pop(guild.id, None)

    def status(self, guild: discord.Guild | None) -> dict[str, Any]:
        if guild is None:
            raise VoiceError("Voice status is available only inside a Discord server.")
        state = self._states.get(guild.id)
        voice_client = guild.voice_client
        connected = bool(voice_client and voice_client.is_connected())
        return {
            "connected": connected,
            "channel": voice_client.channel.mention if connected else "Not connected",
            "speaking": bool(voice_client and voice_client.is_playing()),
            "current": state.current.title if state and state.current else None,
            "requester": state.current.requester_name if state and state.current else None,
            "queued": state.queue.qsize() if state else 0,
        }

    def _controlled_state(
        self, guild: discord.Guild | None, member: discord.Member | discord.User
    ) -> tuple[discord.VoiceClient, GuildVoiceState]:
        if guild is None or not isinstance(member, discord.Member):
            raise VoiceError("Voice controls can only be used inside a Discord server.")
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            raise VoiceError("I am not connected to a voice channel.")
        member_channel = member.voice.channel if member.voice else None
        if member_channel is None or member_channel.id != voice_client.channel.id:
            raise VoiceError("Join my current voice channel before controlling playback.")
        return voice_client, self._state(guild.id)

    def _destination(
        self, guild: discord.Guild | None, member: discord.Member | discord.User
    ) -> discord.abc.Connectable:
        if guild is None or not isinstance(member, discord.Member):
            raise VoiceError("Voice replies can only be used inside a Discord server.")
        destination = member.voice.channel if member.voice else None
        if destination is None:
            raise VoiceError("Join a voice channel first, then try again.")
        me = guild.me
        if me is not None:
            permissions = destination.permissions_for(me)
            if not permissions.connect or not permissions.speak:
                raise VoiceError("I need Connect and Speak permissions in your voice channel.")
        return destination

    async def _connect_locked(
        self, guild: discord.Guild, destination: discord.abc.Connectable
    ) -> discord.VoiceClient:
        voice_client = guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            if voice_client.channel.id != destination.id:
                raise VoiceError(f"I am already helping students in {voice_client.channel.mention}.")
            return voice_client
        try:
            return await destination.connect(timeout=20, reconnect=True)
        except asyncio.TimeoutError as exc:
            raise VoiceError("Connecting to the voice channel timed out.") from exc
        except RuntimeError as exc:
            raise VoiceError("Discord voice support is not installed correctly on this host.") from exc
        except discord.DiscordException as exc:
            raise VoiceError("Discord rejected the voice connection. Check my channel permissions.") from exc

    def _ensure_worker(self, guild_id: int, state: GuildVoiceState) -> None:
        if state.worker is None or state.worker.done():
            state.worker = asyncio.create_task(
                self._worker(guild_id, state), name=f"neetverse-voice-{guild_id}"
            )

    async def _worker(self, guild_id: int, state: GuildVoiceState) -> None:
        try:
            while True:
                try:
                    request = await asyncio.wait_for(state.queue.get(), timeout=self.idle_seconds)
                except asyncio.TimeoutError:
                    async with state.lock:
                        if not state.queue.empty():
                            continue
                        guild = self.bot.get_guild(guild_id)
                        voice_client = guild.voice_client if guild else None
                        if voice_client is not None and voice_client.is_connected():
                            await voice_client.disconnect(force=True)
                        return

                state.current = request
                audio_path = None
                try:
                    audio_path = await self.speech.render(request.text, request.preferences)
                    guild = self.bot.get_guild(guild_id)
                    voice_client = guild.voice_client if guild else None
                    if voice_client is None or not voice_client.is_connected():
                        raise VoiceError("The voice connection closed before playback started.")
                    loop = asyncio.get_running_loop()
                    finished: asyncio.Future[None] = loop.create_future()

                    def after_playback(error: Exception | None) -> None:
                        loop.call_soon_threadsafe(_finish_audio, finished, error)

                    voice_client.play(discord.FFmpegPCMAudio(str(audio_path)), after=after_playback)
                    await asyncio.wait_for(finished, timeout=900)
                    state.last = request
                except asyncio.CancelledError:
                    raise
                except (SpeechError, VoiceError, discord.DiscordException, asyncio.TimeoutError) as exc:
                    logger.warning("Voice playback failed in guild %s: %s", guild_id, exc)
                    await self._report_failure(request.text_channel_id)
                except Exception:
                    logger.exception("Unexpected voice playback failure in guild %s", guild_id)
                    await self._report_failure(request.text_channel_id)
                finally:
                    self.speech.cleanup(audio_path)
                    state.current = None
                    state.queue.task_done()
        except asyncio.CancelledError:
            return
        finally:
            state.worker = None

    async def _report_failure(self, channel_id: int) -> None:
        channel = self.bot.get_channel(int(channel_id))
        if channel is None or not hasattr(channel, "send"):
            return
        try:
            await channel.send(
                "⚠️ Voice playback failed. The text transcript is still available above.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.DiscordException:
            logger.debug("Could not report voice failure in channel %s", channel_id)

    async def close(self) -> None:
        workers = [state.worker for state in self._states.values() if state.worker and not state.worker.done()]
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        for voice_client in tuple(self.bot.voice_clients):
            try:
                await voice_client.disconnect(force=True)
            except discord.DiscordException:
                logger.debug("Voice disconnect failed during shutdown", exc_info=True)
        self._states.clear()


def _finish_audio(future: asyncio.Future[None], error: Exception | None) -> None:
    if future.done():
        return
    if error is None:
        future.set_result(None)
    else:
        future.set_exception(error)
