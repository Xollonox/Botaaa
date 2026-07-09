"""Owner moderation commands: ban, unban, mute, unmute (game/bot level only)."""

from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands
from bot.utils.checks import is_owner, is_registered
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply



class ModerationOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ─── Ban ────────────────────────────────────────────────────────────────

    @commands.command(name="o_ban")
    async def o_ban(
        self,
        ctx: commands.Context,
        target: discord.User,
        reason: str = "No reason provided.",
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> bool:
            if not is_registered(data, target_id):
                return False
            user = data["players"][target_id]["user"]
            user["is_banned"] = True
            user["ban_reason"] = str(reason)
            return True

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            await smart_reply(
                ctx,
                embed=make_embed(data, f"{e('warning', data)} User Not Registered", f"{target.mention} is not registered in the bot."),
                ephemeral=True,
            )
            return

        # Drop stale ToS-acceptance cache so the banned user is re-gated
        # if they are ever unbanned or if their record is later reset.
        invalidate = getattr(self.bot, "invalidate_terms_cache", None)
        if callable(invalidate):
            invalidate(target.id)

        embed = make_embed(
            data,
            f"{e('no', data)} User Banned",
            f"{target.mention} has been banned from using the bot.",
            fields=[
                ("User", f"{target.mention}\n`{target.id}`", True),
                ("Reason", reason, True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)

    # ─── Unban ──────────────────────────────────────────────────────────────

    @commands.command(name="o_unban")
    async def o_unban(
        self,
        ctx: commands.Context,
        target: discord.User,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, bool]:
            if not is_registered(data, target_id):
                return False, False
            user = data["players"][target_id]["user"]
            was_banned = bool(user.get("is_banned", False))
            user["is_banned"] = False
            user.pop("ban_reason", None)
            return True, was_banned

        ok, was_banned = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            await smart_reply(
                ctx,
                embed=make_embed(data, f"{e('warning', data)} User Not Registered", f"{target.mention} is not registered in the bot."),
                ephemeral=True,
            )
            return

        status = "was banned — now unbanned" if was_banned else "was not banned"
        embed = make_embed(
            data,
            f"{e('ok', data)} User Unbanned",
            f"{target.mention} can now use the bot again.",
            fields=[
                ("User", f"{target.mention}\n`{target.id}`", True),
                ("Status", status, True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)

    # ─── Mute ───────────────────────────────────────────────────────────────

    @commands.command(name="o_mute")
    async def o_mute(
        self,
        ctx: commands.Context,
        target: discord.User,
        reason: str = "No reason provided.",
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> bool:
            if not is_registered(data, target_id):
                return False
            user = data["players"][target_id]["user"]
            user["is_muted"] = True
            user["mute_reason"] = str(reason)
            return True

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            await smart_reply(
                ctx,
                embed=make_embed(data, f"{e('warning', data)} User Not Registered", f"{target.mention} is not registered in the bot."),
                ephemeral=True,
            )
            return

        embed = make_embed(
            data,
            "🔇 User Muted",
            f"{target.mention} has been muted from bot interactions.",
            fields=[
                ("User", f"{target.mention}\n`{target.id}`", True),
                ("Reason", reason, True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)

    # ─── Unmute ─────────────────────────────────────────────────────────────

    @commands.command(name="o_unmute")
    async def o_unmute(
        self,
        ctx: commands.Context,
        target: discord.User,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, bool]:
            if not is_registered(data, target_id):
                return False, False
            user = data["players"][target_id]["user"]
            was_muted = bool(user.get("is_muted", False))
            user["is_muted"] = False
            user.pop("mute_reason", None)
            return True, was_muted

        ok, was_muted = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            await smart_reply(
                ctx,
                embed=make_embed(data, f"{e('warning', data)} User Not Registered", f"{target.mention} is not registered in the bot."),
                ephemeral=True,
            )
            return

        status = "was muted — now unmuted" if was_muted else "was not muted"
        embed = make_embed(
            data,
            "🔊 User Unmuted",
            f"{target.mention}'s bot interactions have been restored.",
            fields=[
                ("User", f"{target.mention}\n`{target.id}`", True),
                ("Status", status, True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationOwnerCog(bot))
