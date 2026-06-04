"""Compatibility extension for attack owner commands.

The attack catalog and assignment commands now live under the grouped /o
command in bot.features.cards_admin.
"""

from __future__ import annotations

from discord.ext import commands


class AttacksOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AttacksOwnerCog(bot))
