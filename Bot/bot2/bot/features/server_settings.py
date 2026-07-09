"""Server admin settings commands."""

from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from bot.utils.server_rules import is_admin
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply


class ServerSettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _settings_block(self, data: dict[str, Any]) -> str:
        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        mode = str(settings.get("mode", "all"))
        locked = int(settings.get("locked_channel_id", 0) or 0)
        announce = int(settings.get("announce_channel_id", 0) or 0)
        battle = int(settings.get("battle_channel_id", 0) or 0)
        return box("Server Settings", [
            f"⚙️ Mode: {mode}",
            f"🔒 Locked Channel: {f'<#{locked}>' if locked else 'Not set'}",
            f"📢 Announce Channel: {f'<#{announce}>' if announce else 'Not set'}",
            f"⚔️ Battle Channel: {f'<#{battle}>' if battle else 'Not set'}",
        ])

    @commands.command(name="server_mode")
    async def server_mode(self, ctx: commands.Context, mode: str) -> None:
        data = self.bot.storage.load()
        if not is_admin(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Admin Only", "Not allowed."), ephemeral=True)
            return

        if mode not in ("all", "single"):
            await smart_reply(ctx, embed=make_embed(data, f"{e('warning', data)} Invalid Mode", "Mode must be 'all' or 'single'."), ephemeral=True)
            return

        def mutate(d: dict[str, Any]) -> None:
            settings = d.setdefault("server_settings", {})
            if not isinstance(settings, dict):
                settings = {}
                d["server_settings"] = settings
            settings["mode"] = mode
            settings.setdefault("locked_channel_id", 0)
            settings.setdefault("announce_channel_id", 0)
            settings.setdefault("battle_channel_id", 0)

        self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        note = ""
        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        if mode == "single" and int(settings.get("locked_channel_id", 0) or 0) == 0:
            note = f"\n{e('warning', data)} Set locked channel via !server_set_channel"

        await smart_reply(ctx,
            embed=make_embed(data, f"{e('settings', data)} 𝗦𝗘𝗥𝗩𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦", self._settings_block(data) + note),
            ephemeral=True,
        )

    @commands.command(name="server_set_channel")
    async def server_set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        data = self.bot.storage.load()
        if not is_admin(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Admin Only", "Not allowed."), ephemeral=True)
            return

        self.bot.storage.with_lock(lambda d: d.setdefault("server_settings", {}).update({"locked_channel_id": int(channel.id)}))
        data = self.bot.storage.load()
        await smart_reply(ctx,
            embed=make_embed(data, f"{e('settings', data)} 𝗦𝗘𝗥𝗩𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦", self._settings_block(data)),
            ephemeral=True,
        )

    @commands.command(name="server_set_announce")
    async def server_set_announce(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        data = self.bot.storage.load()
        if not is_admin(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Admin Only", "Not allowed."), ephemeral=True)
            return

        self.bot.storage.with_lock(lambda d: d.setdefault("server_settings", {}).update({"announce_channel_id": int(channel.id)}))
        data = self.bot.storage.load()
        await smart_reply(ctx,
            embed=make_embed(data, f"{e('settings', data)} 𝗦𝗘𝗥𝗩𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦", self._settings_block(data)),
            ephemeral=True,
        )

    @commands.command(name="server_set_battle")
    async def server_set_battle(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        data = self.bot.storage.load()
        if not is_admin(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Admin Only", "Not allowed."), ephemeral=True)
            return

        self.bot.storage.with_lock(lambda d: d.setdefault("server_settings", {}).update({"battle_channel_id": int(channel.id)}))
        data = self.bot.storage.load()
        await smart_reply(ctx,
            embed=make_embed(data, f"{e('settings', data)} 𝗦𝗘𝗥𝗩𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦", self._settings_block(data)),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerSettingsCog(bot))
