import io
import logging
import time
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from commands import _active_users_today, _messages_processed, send_discord_text
from image import (
    build_img2img_edit_prompt,
    detect_chat_image_trigger,
    enhance_image_prompt,
    fetch_url_bytes,
    generate_bluesminds_image,
    generate_free_image,
    generate_image_bytes,
    gather_image_urls,
    improve_image_prompt,
    maybe_image_trigger_prompt,
    vision_reply_for_message,
)
from llm import chat_with_fallback
from memory import (
    _should_summarize,
    get_channel_context,
    get_mood,
    remember_channel_line,
    remember_line,
    update_conversation_summary,
)
from persona import (
    build_system_prompt,
    build_user_prompt_with_lore,
    detect_language,
    is_apology,
    is_lookism_query,
    is_roast,
    set_friend,
    set_roasting,
)

logger = logging.getLogger("misskim")

_user_message_times: Dict[int, list] = {}
# generated image message id -> {prompt, raw_prompt, backend}
generated_image_messages: Dict[int, dict] = {}


def _is_rate_limited(user_id: int) -> bool:
    now = time.time()
    times = _user_message_times.setdefault(user_id, [])
    times = [t for t in times if now - t < 10]
    _user_message_times[user_id] = times
    if len(times) >= 5:
        return True
    times.append(now)
    return False


def _build_full_user_prompt(
    text: str,
    user_id: int,
    guild_id: Optional[int],
    channel_id: int,
) -> str:
    from memory import add_memory_to_prompt

    lore_prompt = build_user_prompt_with_lore(text)
    return add_memory_to_prompt(
        user_id, lore_prompt, guild_id=guild_id, channel_id=channel_id
    )


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        from memory import BOT_MEMORY, BOT_SETTINGS, _save_json_file
        from config import MEMORY_FILE, SETTINGS_FILE

        logger.info(
            "Logged in as %s (id=%s)",
            self.bot.user,
            getattr(self.bot.user, "id", "unknown"),
        )
        _save_json_file(MEMORY_FILE, BOT_MEMORY)
        _save_json_file(SETTINGS_FILE, BOT_SETTINGS)
        try:
            await self.bot.tree.sync()
        except Exception:
            logger.exception("Failed to sync slash commands")

    @commands.Cog.listener()
    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("Unhandled Discord event error | event=%s", event_method)

    @commands.Cog.listener()
    async def on_disconnect(self) -> None:
        logger.warning("Bot disconnected from Discord.")

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        logger.exception(
            "Prefix/hybrid command failed | command=%s user=%s guild=%s channel=%s",
            getattr(ctx.command, "qualified_name", "unknown"),
            getattr(ctx.author, "id", "unknown"),
            getattr(ctx.guild, "id", None),
            getattr(ctx.channel, "id", None),
            exc_info=error,
        )

    @commands.Cog.listener()
    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        logger.exception(
            "Slash command failed | command=%s user=%s guild=%s channel=%s",
            getattr(
                getattr(interaction, "command", None), "qualified_name", "unknown"
            ),
            getattr(interaction.user, "id", "unknown"),
            interaction.guild_id,
            interaction.channel_id,
            exc_info=error,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        global _messages_processed

        if message.author.bot:
            return

        _messages_processed += 1
        _active_users_today.add(message.author.id)

        if _is_rate_limited(message.author.id):
            return

        if not await self._can_send(message):
            await self.bot.process_commands(message)
            return

        content_raw = message.content.strip()
        user_id = message.author.id
        guild_id = message.guild.id if message.guild else None
        channel_id = message.channel.id
        mood = get_mood(channel_id)

        # 1. Sorry / roast detection
        if is_apology(content_raw):
            set_friend(user_id)
        elif is_roast(content_raw):
            set_roasting(user_id)

        # 2. @pollo / @imagine chat triggers
        handled = await self._handle_chat_image_trigger(
            message, content_raw, guild_id, channel_id
        )
        if handled:
            await self.bot.process_commands(message)
            return

        # 3. Reply-to-generated-image (user wants to improve)
        handled = await self._handle_image_reply(
            message, content_raw, guild_id, channel_id
        )
        if handled:
            await self.bot.process_commands(message)
            return

        # 4. Keyword image triggers ("create image ...", "imagine ...")
        handled = await self._handle_image_keyword(
            message, content_raw, guild_id, channel_id
        )
        if handled:
            await self.bot.process_commands(message)
            return

        # 5. Bot mention or direct reply to bot → full chat response
        is_mention = bool(self.bot.user and self.bot.user in message.mentions)
        is_reply_to_bot = self._is_reply_to_bot(message)
        is_dm = message.guild is None

        if is_mention or is_reply_to_bot or is_dm:
            await self._handle_chat(
                message, content_raw, user_id, guild_id, channel_id, mood
            )

        await self.bot.process_commands(message)

    # ─── helpers ─────────────────────────────────────────────────────────────

    async def _can_send(self, message: discord.Message) -> bool:
        if message.guild is None:
            return True
        me = getattr(message.guild, "me", None)
        if me is None or not isinstance(message.author, discord.Member):
            return False
        return message.channel.permissions_for(me).send_messages

    def _is_reply_to_bot(self, message: discord.Message) -> bool:
        if not message.reference or not message.reference.resolved:
            return False
        resolved = message.reference.resolved
        if not isinstance(resolved, discord.Message):
            return False
        return bool(self.bot.user and resolved.author.id == self.bot.user.id)

    async def _handle_chat_image_trigger(
        self,
        message: discord.Message,
        content_raw: str,
        guild_id: Optional[int],
        channel_id: int,
    ) -> bool:
        chat_img = detect_chat_image_trigger(content_raw)
        if not chat_img:
            return False
        backend, raw_prompt = chat_img
        source_bytes, source_url = await self._read_first_attachment(message)
        enhanced = await enhance_image_prompt(
            raw_prompt,
            image_url=source_url,
            user_id=message.author.id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        generated = await self._generate(backend, enhanced, source_bytes)
        if generated:
            buf = io.BytesIO(generated)
            buf.seek(0)
            label = "Pollinations" if backend == "pollinations" else "BluesMinds" if backend == "bluesminds" else "Cloudflare"
            sent = await send_discord_text(
                message.channel.send,
                f"{label} | Prompt: {enhanced}",
                file=discord.File(buf, filename="generated.png"),
            )
            generated_image_messages[sent.id] = {
                "prompt": enhanced,
                "raw_prompt": raw_prompt,
                "backend": backend,
            }
        else:
            await send_discord_text(
                message.channel.send,
                "Couldn't generate that image, try a different prompt.",
            )
        return True

    async def _handle_image_reply(
        self,
        message: discord.Message,
        content_raw: str,
        guild_id: Optional[int],
        channel_id: int,
    ) -> bool:
        if not message.reference or not message.reference.resolved:
            return False
        resolved = message.reference.resolved
        if not (
            isinstance(resolved, discord.Message)
            and self.bot.user
            and resolved.author.id == self.bot.user.id
            and resolved.id in generated_image_messages
        ):
            return False

        img_meta = generated_image_messages[resolved.id]
        original_prompt = img_meta["prompt"]
        backend = img_meta["backend"]
        user_feedback = content_raw.strip() or "improve"
        ref_image_url: Optional[str] = (
            resolved.attachments[0].url if resolved.attachments else None
        )

        improved = await improve_image_prompt(
            original_prompt=original_prompt,
            user_feedback=user_feedback,
            image_url=ref_image_url,
            user_id=message.author.id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        ref_bytes = await fetch_url_bytes(ref_image_url) if ref_image_url else None
        generated = await self._generate(backend, improved, ref_bytes)

        if generated:
            buf = io.BytesIO(generated)
            buf.seek(0)
            label = "Pollinations" if backend == "pollinations" else "BluesMinds" if backend == "bluesminds" else "Cloudflare"
            sent = await send_discord_text(
                message.channel.send,
                f"{label} | Improved prompt: {improved}",
                file=discord.File(buf, filename="improved.png"),
                reference=message,
            )
            generated_image_messages[sent.id] = {
                "prompt": improved,
                "raw_prompt": improved,
                "backend": backend,
            }
        else:
            await send_discord_text(
                message.reply,
                "Couldn't regenerate that. Try describing what to change differently.",
                mention_author=False,
            )
        return True

    async def _handle_image_keyword(
        self,
        message: discord.Message,
        content_raw: str,
        guild_id: Optional[int],
        channel_id: int,
    ) -> bool:
        image_prompt = maybe_image_trigger_prompt(content_raw)
        if not image_prompt:
            return False
        source_bytes, source_url = await self._read_first_attachment(message)
        effective_prompt = image_prompt
        if source_url:
            effective_prompt = await build_img2img_edit_prompt(
                user_prompt=image_prompt,
                image_url=source_url,
                user_id=message.author.id,
                guild_id=guild_id,
                channel_id=channel_id,
            )
        generated = await generate_image_bytes(
            prompt=effective_prompt, source_image_bytes=source_bytes
        )
        if generated:
            buf = io.BytesIO(generated)
            buf.seek(0)
            await send_discord_text(
                message.channel.send,
                f"Image prompt: {effective_prompt}",
                file=discord.File(buf, filename="chat-image.png"),
            )
        else:
            logger.warning(
                "Image keyword trigger returned no bytes | user=%s prompt=%s",
                message.author.id,
                effective_prompt[:120],
            )
            await send_discord_text(
                message.channel.send,
                "Could not generate image for that prompt.",
            )
        return True

    async def _handle_chat(
        self,
        message: discord.Message,
        content_raw: str,
        user_id: int,
        guild_id: Optional[int],
        channel_id: int,
        mood: str,
    ) -> None:
        await remember_line(
            user_id, "U", content_raw, guild_id=guild_id, channel_id=channel_id
        )
        # Store in channel-level memory so other users see the context
        if guild_id is not None:
            await remember_channel_line(
                channel_id,
                speaker_name=message.author.display_name,
                prefix="U",
                line=content_raw,
                guild_id=guild_id,
            )

        image_reply = await vision_reply_for_message(message, mood=mood)
        if image_reply:
            reply = image_reply
        else:
            lang = detect_language(content_raw, channel_id=channel_id)
            system = build_system_prompt(user_id, mood, lang)
            reply = await chat_with_fallback(
                system_prompt=system,
                user_prompt=_build_full_user_prompt(
                    content_raw, user_id, guild_id, channel_id
                ),
                prefer_search=is_lookism_query(content_raw),
            )

        if not reply.strip():
            reply = "I am here. Ask me anything."

        await send_discord_text(message.channel.send, reply)
        await remember_line(
            user_id, "B", reply, guild_id=guild_id, channel_id=channel_id
        )
        # Also store bot reply in channel-level memory
        if guild_id is not None:
            bot_name = self.bot.user.display_name if self.bot.user else "Miss Kim"
            await remember_channel_line(
                channel_id,
                speaker_name=bot_name,
                prefix="B",
                line=reply,
                guild_id=guild_id,
            )
        if _should_summarize(user_id, guild_id=guild_id, channel_id=channel_id):
            await update_conversation_summary(
                user_id, guild_id=guild_id, channel_id=channel_id
            )

    @staticmethod
    async def _read_first_attachment(
        message: discord.Message,
    ) -> tuple:
        """Return (bytes, url) for the first image attachment, or (None, None)."""
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                try:
                    data = await att.read()
                    return data, att.url
                except Exception:
                    logger.warning(
                        "Failed to read attachment | url=%s", att.url
                    )
                    continue
        return None, None

    @staticmethod
    async def _generate(
        backend: str, prompt: str, source_bytes: Optional[bytes]
    ) -> Optional[bytes]:
        if backend == "pollinations":
            return await generate_free_image(prompt)
        if backend == "bluesminds":
            result = await generate_bluesminds_image(prompt)
            if result:
                return result
            logger.warning("BluesMinds failed, falling back to Cloudflare")
            return await generate_image_bytes(
                prompt=prompt, source_image_bytes=source_bytes
            )
        return await generate_image_bytes(
            prompt=prompt, source_image_bytes=source_bytes
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventsCog(bot))
