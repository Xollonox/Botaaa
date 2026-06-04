"""Owner manual announcement command."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import OWNER_GUILD_ID
from bot.utils.checks import is_owner
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class AnnounceOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="o_announce", description="Owner: manually post an announcement.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_announce(
        self,
        interaction: discord.Interaction,
        message: str,
        title: str | None = None,
        image_url: str | None = None,
        ping_role: discord.Role | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        announce_channel_id = int(settings.get("announce_channel_id", 0) or 0)

        target_channel = interaction.channel
        if announce_channel_id > 0:
            target_channel = self.bot.get_channel(announce_channel_id)
            if target_channel is None:
                try:
                    target_channel = await self.bot.fetch_channel(announce_channel_id)
                except Exception:
                    target_channel = interaction.channel

        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            await smart_reply(interaction, 
                embed=make_embed(data, f"{e('warning', data)} Announcement Failed", "Target channel unavailable."),
                ephemeral=True,
            )
            return

        embed = make_embed(
            data,
            f"{e('announce', data)} {title.strip() if isinstance(title, str) and title.strip() else 'Announcement'}",
            str(message),
        )
        embed.set_footer(text="Server Announcement")
        if isinstance(image_url, str) and image_url.strip():
            embed.set_image(url=image_url.strip())

        content = ping_role.mention if ping_role is not None else None
        posted = await target_channel.send(content=content, embed=embed)

        await smart_reply(interaction, 
            embed=make_embed(
                data,
                f"{e('ok', data)} Announcement Posted",
                f"{e('channel', data)} {target_channel.mention}\n{e('link', data)} {posted.jump_url}",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnounceOwnerCog(bot))
