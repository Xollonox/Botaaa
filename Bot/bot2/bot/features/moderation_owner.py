"""Owner moderation commands: ban, unban, mute, unmute (game/bot level only)."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from bot.config import OWNER_GUILD_ID

from bot.utils.checks import is_owner, is_registered
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class ModerationOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ─── Ban ────────────────────────────────────────────────────────────────

    @app_commands.command(name="o_ban", description="Owner: ban a user from using the bot (game level).")
    @app_commands.guilds(OWNER_GUILD)
    async def o_ban(
        self,
        interaction: discord.Interaction,
        target: discord.User,
        reason: str = "No reason provided.",
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
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
                interaction,
                embed=make_embed(data, f"{e('warning', data)} User Not Registered", f"{target.mention} is not registered in the bot."),
                ephemeral=True,
            )
            return

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
        await smart_reply(interaction, embed=embed, ephemeral=True)

    # ─── Unban ──────────────────────────────────────────────────────────────

    @app_commands.command(name="o_unban", description="Owner: unban a user from the bot.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_unban(
        self,
        interaction: discord.Interaction,
        target: discord.User,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
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
                interaction,
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
        await smart_reply(interaction, embed=embed, ephemeral=True)

    # ─── Mute ───────────────────────────────────────────────────────────────

    @app_commands.command(name="o_mute", description="Owner: mute a user (restrict bot interactions at game level).")
    @app_commands.guilds(OWNER_GUILD)
    async def o_mute(
        self,
        interaction: discord.Interaction,
        target: discord.User,
        reason: str = "No reason provided.",
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
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
                interaction,
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
        await smart_reply(interaction, embed=embed, ephemeral=True)

    # ─── Unmute ─────────────────────────────────────────────────────────────

    @app_commands.command(name="o_unmute", description="Owner: unmute a user.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_unmute(
        self,
        interaction: discord.Interaction,
        target: discord.User,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Access Denied", "This command is restricted to bot owners only."), ephemeral=True)
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
                interaction,
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
        await smart_reply(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationOwnerCog(bot))
