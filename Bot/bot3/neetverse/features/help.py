"""Mobile-first system navigator for NeetVerse."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.guide import GUIDE_PAGES
from neetverse.ui import embed, progress_bar, reply


def help_embed(index: int) -> discord.Embed:
    title, description = GUIDE_PAGES[index]
    header = (
        f"{progress_bar(index + 1, len(GUIDE_PAGES), width=10)}  "
        f"`SYSTEM {index + 1:02d}/{len(GUIDE_PAGES):02d}`\n\n"
    )
    value = embed(title, header + description)
    value.set_footer(text="NEETVERSE  •  SELECT A SYSTEM BELOW  •  MOBILE COMMAND DECK")
    return value


class HelpSelect(discord.ui.Select):
    def __init__(self, view: "HelpView") -> None:
        options = [discord.SelectOption(
            label=title.split(" ", 1)[1], value=str(index), emoji=title.split(" ", 1)[0]
        ) for index, (title, _) in enumerate(GUIDE_PAGES)]
        super().__init__(placeholder="Choose a NeetVerse system…", options=options)
        self.help_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        index = int(self.values[0])
        await interaction.response.edit_message(embed=help_embed(index), view=self.help_view)


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
        await interaction.response.send_message(
            embed=help_embed(0), view=HelpView(interaction.user.id), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
