"""Mobile-first system navigator for NeetVerse."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.guide import GUIDE_PAGES
from neetverse.ui import embed, reply


class HelpSelect(discord.ui.Select):
    def __init__(self, view: "HelpView") -> None:
        options = [discord.SelectOption(
            label=title.split(" ", 1)[1], value=str(index), emoji=title.split(" ", 1)[0]
        ) for index, (title, _) in enumerate(GUIDE_PAGES)]
        super().__init__(placeholder="Choose a NeetVerse system…", options=options)
        self.help_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        title, description = GUIDE_PAGES[int(self.values[0])]
        await interaction.response.edit_message(embed=embed(title, description), view=self.help_view)


class HelpView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=600)
        self.user_id = str(user_id)
        self.add_item(HelpSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="This help panel belongs to another student.")
            return False
        return True


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Explore NeetVerse systems and daily workflows.")
    async def help(self, interaction: discord.Interaction) -> None:
        title, description = GUIDE_PAGES[0]
        await interaction.response.send_message(
            embed=embed(title, description), view=HelpView(interaction.user.id), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
