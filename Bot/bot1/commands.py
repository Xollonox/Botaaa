import io
import logging
from datetime import datetime, timezone
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import SPECIAL_USER_ID
from image import (
    build_img2img_edit_prompt,
    fetch_perchance_output,
    generate_free_image,
    generate_image_bytes,
    vision_chat_from_urls,
)
from llm import chat_with_fallback
from memory import (
    BOT_MEMORY,
    BOT_SETTINGS,
    _should_summarize,
    clear_all_memory,
    clear_user_memory,
    get_language_setting,
    get_mood,
    remember_channel_line,
    remember_line,
    set_language_setting,
    set_mood,
    update_conversation_summary,
)
from persona import (
    VALID_MOODS,
    build_system_prompt,
    build_user_prompt_with_lore,
    detect_language,
    is_lookism_query,
)

logger = logging.getLogger("misskim")

# Bot-level stats shared with events.py
_bot_start_time = datetime.now(timezone.utc)
_messages_processed: int = 0
_active_users_today: set = set()


def is_power_user(user: discord.abc.User) -> bool:
    if getattr(user, "id", None) == SPECIAL_USER_ID:
        return True
    if isinstance(user, discord.Member):
        return bool(
            getattr(user, "guild_permissions", None)
            and user.guild_permissions.administrator
        )
    return False


def split_discord_text(text: str, limit: int = 2000) -> List[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return [""]
    chunks: List[str] = []
    while len(cleaned) > limit:
        cut = cleaned.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = cleaned.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunk = cleaned[:cut].rstrip()
        if not chunk:
            chunk = cleaned[:limit]
            cut = limit
        chunks.append(chunk)
        cleaned = cleaned[cut:].lstrip("\n ")
    if cleaned:
        chunks.append(cleaned)
    return chunks


async def send_discord_text(
    send_func,
    text: str,
    *,
    limit: int = 2000,
    file: Optional[discord.File] = None,
    **kwargs,
):
    chunks = split_discord_text(text, limit=limit)
    if len(chunks) == 1:
        if file is not None:
            return await send_func(chunks[0], file=file, **kwargs)
        return await send_func(chunks[0], **kwargs)
    first = True
    result = None
    for chunk in chunks:
        if first and file is not None:
            result = await send_func(chunk, file=file, **kwargs)
        else:
            result = await send_func(chunk, **kwargs)
        first = False
    return result


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


class ResetMemoryView(discord.ui.View):
    def __init__(self, requester_id: int, allow_all: bool) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.allow_all = allow_all

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This button is not for you.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Reset My Memory", style=discord.ButtonStyle.danger)
    async def reset_mine(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._guard(interaction):
            return
        clear_user_memory(
            interaction.user.id,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
        )
        await interaction.response.edit_message(
            content="Your memory was reset.", view=None
        )

    @discord.ui.button(label="Reset All Memory", style=discord.ButtonStyle.danger)
    async def reset_all(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._guard(interaction):
            return
        if not self.allow_all:
            await interaction.response.send_message(
                "You do not have permission for global reset.", ephemeral=True
            )
            return
        clear_all_memory()
        await interaction.response.edit_message(
            content="All bot memory was reset.", view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(content="Cancelled.", view=None)


class CommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /ask ─────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="ask", description="Ask Miss Kim anything")
    async def ask(self, ctx: commands.Context, *, question: str) -> None:
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(thinking=True)

        guild_id = ctx.guild.id if ctx.guild else None
        channel_id = ctx.channel.id
        lang = detect_language(question, channel_id=channel_id)
        mood = get_mood(channel_id)
        system = build_system_prompt(ctx.author.id, mood, lang)

        await remember_line(
            ctx.author.id, "U", question, guild_id=guild_id, channel_id=channel_id
        )
        # Store in channel-level memory
        if guild_id is not None:
            await remember_channel_line(
                channel_id,
                speaker_name=ctx.author.display_name,
                prefix="U",
                line=question,
                guild_id=guild_id,
            )
        reply = await chat_with_fallback(
            system_prompt=system,
            user_prompt=_build_full_user_prompt(
                question, ctx.author.id, guild_id, channel_id
            ),
            prefer_search=is_lookism_query(question),
        )
        await remember_line(
            ctx.author.id, "B", reply, guild_id=guild_id, channel_id=channel_id
        )
        # Store bot reply in channel-level memory
        if guild_id is not None:
            bot_name = self.bot.user.display_name if self.bot.user else "Miss Kim"
            await remember_channel_line(
                channel_id,
                speaker_name=bot_name,
                prefix="B",
                line=reply,
                guild_id=guild_id,
            )
        if _should_summarize(ctx.author.id, guild_id=guild_id, channel_id=channel_id):
            await update_conversation_summary(
                ctx.author.id, guild_id=guild_id, channel_id=channel_id
            )
        if ctx.interaction:
            await send_discord_text(ctx.interaction.followup.send, reply)
        else:
            await send_discord_text(ctx.reply, reply, mention_author=False)

    # ── !kim ─────────────────────────────────────────────────────────────────
    @commands.command(name="kim")
    async def kim(self, ctx: commands.Context, *, text: str = "") -> None:
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(thinking=True)

        prompt = text.strip() or "Start a conversation to make this chat active right now."
        guild_id = ctx.guild.id if ctx.guild else None
        channel_id = ctx.channel.id
        lang = detect_language(prompt, channel_id=channel_id)
        mood = get_mood(channel_id)
        system = build_system_prompt(ctx.author.id, mood, lang)

        await remember_line(
            ctx.author.id, "U", prompt, guild_id=guild_id, channel_id=channel_id
        )
        # Store in channel-level memory
        if guild_id is not None:
            await remember_channel_line(
                channel_id,
                speaker_name=ctx.author.display_name,
                prefix="U",
                line=prompt,
                guild_id=guild_id,
            )
        reply = await chat_with_fallback(
            system_prompt=system,
            user_prompt=_build_full_user_prompt(
                prompt, ctx.author.id, guild_id, channel_id
            ),
            prefer_search=is_lookism_query(prompt),
        )
        await remember_line(
            ctx.author.id, "B", reply, guild_id=guild_id, channel_id=channel_id
        )
        # Store bot reply in channel-level memory
        if guild_id is not None:
            bot_name = self.bot.user.display_name if self.bot.user else "Miss Kim"
            await remember_channel_line(
                channel_id,
                speaker_name=bot_name,
                prefix="B",
                line=reply,
                guild_id=guild_id,
            )
        if _should_summarize(ctx.author.id, guild_id=guild_id, channel_id=channel_id):
            await update_conversation_summary(
                ctx.author.id, guild_id=guild_id, channel_id=channel_id
            )
        if ctx.interaction:
            await send_discord_text(ctx.interaction.followup.send, reply)
        else:
            await send_discord_text(ctx.reply, reply, mention_author=False)

    # ── /imagine ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="imagine",
        description="Generate an image from prompt (optional image for img2img)",
    )
    @app_commands.describe(prompt="Image prompt", image="Optional source image")
    async def imagine(
        self,
        interaction: discord.Interaction,
        prompt: str,
        image: Optional[discord.Attachment] = None,
    ) -> None:
        await self._run_slash_image(interaction=interaction, prompt=prompt, image=image)

    # ── /image ────────────────────────────────────────────────────────────────
    @app_commands.command(
        name="image",
        description="Generate an image from prompt (optional image for img2img)",
    )
    @app_commands.describe(prompt="Image prompt", image="Optional source image")
    async def image(
        self,
        interaction: discord.Interaction,
        prompt: str,
        image: Optional[discord.Attachment] = None,
    ) -> None:
        await self._run_slash_image(interaction=interaction, prompt=prompt, image=image)

    async def _run_slash_image(
        self,
        interaction: discord.Interaction,
        prompt: str,
        image: Optional[discord.Attachment] = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        source_bytes: Optional[bytes] = None
        effective_prompt = prompt
        if image is not None and (image.content_type or "").startswith("image/"):
            source_bytes = await image.read()
            effective_prompt = await build_img2img_edit_prompt(
                user_prompt=prompt,
                image_url=image.url,
                user_id=interaction.user.id,
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
            )
        generated = await generate_image_bytes(
            prompt=effective_prompt, source_image_bytes=source_bytes
        )
        if not generated:
            logger.warning(
                "Slash image generation failed | user=%s prompt=%s",
                interaction.user.id,
                effective_prompt[:120],
            )
            await send_discord_text(
                interaction.followup.send,
                "Image generation failed. Try a shorter prompt.",
            )
            return
        buf = io.BytesIO(generated)
        buf.seek(0)
        file = discord.File(buf, filename="imagine.png")
        await send_discord_text(
            interaction.followup.send,
            f"Prompt: {effective_prompt}",
            file=file,
        )

    # ── /vision ───────────────────────────────────────────────────────────────
    @app_commands.command(
        name="vision", description="Analyze an image attachment with Miss Kim vision"
    )
    @app_commands.describe(
        image="Image to analyze", question="Optional question about the image"
    )
    async def vision(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment,
        question: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        if not (image.content_type or "").startswith("image/"):
            await send_discord_text(
                interaction.followup.send, "Attach a valid image file."
            )
            return
        prompt_text = question or "Describe this image clearly and mention important details."
        mood = get_mood(interaction.channel_id)
        reply = await vision_chat_from_urls(
            user_text=prompt_text,
            image_urls=[image.url],
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            mood=mood,
        )
        await send_discord_text(
            interaction.followup.send, reply or "Could not analyze this image."
        )

    # ── /pollo ────────────────────────────────────────────────────────────────
    @app_commands.command(
        name="pollo", description="Generate AI image with Pollinations"
    )
    @app_commands.describe(prompt="Describe the image you want")
    async def pollo(
        self, interaction: discord.Interaction, prompt: str
    ) -> None:
        await interaction.response.defer(thinking=True)
        generated = await generate_free_image(prompt)
        if not generated:
            logger.warning(
                "Pollo generation failed | user=%s prompt=%s",
                interaction.user.id,
                prompt[:120],
            )
            await send_discord_text(
                interaction.followup.send,
                "Image generation failed. Try a different prompt.",
            )
            return
        buf = io.BytesIO(generated)
        buf.seek(0)
        file = discord.File(buf, filename="free-ai.png")
        await send_discord_text(
            interaction.followup.send,
            f"**Free AI Image**\nPrompt: {prompt}",
            file=file,
        )

    # ── /perchance ────────────────────────────────────────────────────────────
    @commands.hybrid_command(
        name="perchance",
        description="Fetch a random output from a Perchance generator list",
    )
    @app_commands.describe(
        generator="The URL segment name of the generator",
        list_name="Specific list name inside the generator (defaults to 'output')",
    )
    async def perchance(
        self, ctx: commands.Context, generator: str, list_name: str = "output"
    ) -> None:
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer()
        else:
            await ctx.trigger_typing()
        result = await fetch_perchance_output(generator, list_name)
        await send_discord_text(
            ctx.reply if ctx.interaction else ctx.send,
            result,
            mention_author=False,
        )

    # ── /reset_memory ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="reset_memory", description="Reset Miss Kim memory (button confirmation)"
    )
    async def reset_memory(self, interaction: discord.Interaction) -> None:
        allow_all = is_power_user(interaction.user)
        view = ResetMemoryView(
            requester_id=interaction.user.id, allow_all=allow_all
        )
        await interaction.response.send_message(
            "Choose memory reset action:", view=view, ephemeral=True
        )

    # ── /language ─────────────────────────────────────────────────────────────
    @commands.hybrid_command(
        name="language", description="Set bot reply language for this channel"
    )
    @app_commands.describe(lang="Language mode")
    @app_commands.choices(
        lang=[
            app_commands.Choice(name="Auto (auto-detect)", value="auto"),
            app_commands.Choice(name="English", value="en"),
            app_commands.Choice(name="Hinglish", value="hinglish"),
        ]
    )
    async def language(
        self, ctx: commands.Context, lang: app_commands.Choice[str]
    ) -> None:
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(ephemeral=True)
        set_language_setting(ctx.channel.id, lang.value)
        await ctx.send(f"Language set to **{lang.name}** in this channel.")

    # ── /mood ─────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="mood", description="Change Miss Kim mood")
    @app_commands.describe(mood="Select a mood")
    @app_commands.choices(
        mood=[
            app_commands.Choice(name=m.capitalize(), value=m)
            for m in sorted(VALID_MOODS)
        ]
    )
    async def mood(
        self, ctx: commands.Context, mood: app_commands.Choice[str]
    ) -> None:
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(ephemeral=True)
        if not is_power_user(ctx.author):
            await ctx.send("You do not have permission.")
            return
        if mood.value not in VALID_MOODS:
            await ctx.send(
                f"Invalid mood. Valid options: {', '.join(sorted(VALID_MOODS))}"
            )
            return
        set_mood(ctx.channel.id, mood.value)
        await ctx.send(f"Miss Kim mood set to **{mood.name}** in this channel.")

    # ── /roast ────────────────────────────────────────────────────────────────
    @app_commands.command(name="roast", description="Set Miss Kim to roast mode")
    @app_commands.describe(level="Roast intensity")
    @app_commands.choices(
        level=[
            app_commands.Choice(name="🔥 Low — mild teasing", value="roast_low"),
            app_commands.Choice(name="🔥🔥 Medium — spicy shade", value="roast_medium"),
            app_commands.Choice(name="🔥🔥🔥 Extreme — no filter, all out", value="roast_extreme"),
        ]
    )
    async def roast(
        self, interaction: discord.Interaction, level: app_commands.Choice[str]
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        if not is_power_user(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        set_mood(interaction.channel_id, level.value)
        emoji = {"roast_low": "🔥", "roast_medium": "🔥🔥", "roast_extreme": "🔥🔥🔥"}
        msg = (
            f"{emoji.get(level.value, '🔥')} Roast mode set to **{level.name}**. "
            + ("Let em have it." if level.value == "roast_extreme" else "Go easy... kinda.")
        )
        await interaction.response.send_message(msg)

    # ── /angry ────────────────────────────────────────────────────────────────
    @app_commands.command(name="angry", description="Set Miss Kim mood to angry")
    async def angry(self, interaction: discord.Interaction) -> None:
        if not is_power_user(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        set_mood(interaction.channel_id, "angry")
        await interaction.response.send_message("😤 Mood set to **Angry**. Watch your mouth.")

    # ── /sad ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="sad", description="Set Miss Kim mood to sad")
    async def sad(self, interaction: discord.Interaction) -> None:
        if not is_power_user(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        set_mood(interaction.channel_id, "sad")
        await interaction.response.send_message("😢 Mood set to **Sad**. Feeling down today...")

    # ── /happy ────────────────────────────────────────────────────────────────
    @app_commands.command(name="happy", description="Set Miss Kim mood to happy")
    async def happy(self, interaction: discord.Interaction) -> None:
        if not is_power_user(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        set_mood(interaction.channel_id, "happy")
        await interaction.response.send_message("😊 Mood set to **Happy**! Let's have some fun!")

    # ── /purge ────────────────────────────────────────────────────────────────
    @commands.command(name="purge")
    async def purge(self, ctx: commands.Context, amount: int = 10) -> None:
        if not is_power_user(ctx.author):
            await ctx.reply("You do not have permission.", mention_author=False)
            return
        amount = max(1, min(amount, 200))
        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"Deleted {len(deleted) - 1} messages.", delete_after=5)

    # ── !say ──────────────────────────────────────────────────────────────────
    @commands.command(name="say")
    async def say(self, ctx: commands.Context, *, text: str) -> None:
        if not is_power_user(ctx.author):
            await ctx.reply("You do not have permission.", mention_author=False)
            return
        await ctx.message.delete()
        await send_discord_text(ctx.send, text)

    # ── /stats ────────────────────────────────────────────────────────────────
    @app_commands.command(name="stats", description="Show bot statistics")
    async def stats(self, interaction: discord.Interaction) -> None:
        uptime = datetime.now(timezone.utc) - _bot_start_time
        uptime_str = (
            f"{uptime.days}d "
            f"{uptime.seconds // 3600}h "
            f"{(uptime.seconds // 60) % 60}m"
        )
        memory_entries = sum(
            len(state.get("lines", []))
            for state in BOT_MEMORY.get("users", {}).values()
        )
        current_mood = get_mood(interaction.channel_id)
        active_count = len(_active_users_today)

        embed = discord.Embed(
            title="Miss Kim Bot Statistics",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(
            name="Messages Processed", value=str(_messages_processed), inline=True
        )
        embed.add_field(
            name="Memory Entries", value=str(memory_entries), inline=True
        )
        embed.add_field(
            name="Current Mood", value=current_mood.capitalize(), inline=True
        )
        embed.add_field(
            name="Active Users Today", value=str(active_count), inline=True
        )
        embed.set_footer(text="Last updated")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommandsCog(bot))
