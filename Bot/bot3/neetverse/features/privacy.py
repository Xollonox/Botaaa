"""Private export and guarded deletion controls."""

from __future__ import annotations

import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ui import ERROR, SUCCESS, embed, reply


class DeleteDataView(discord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = str(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await reply(interaction, content="This deletion confirmation belongs to another student.")
            return False
        return True

    @discord.ui.button(label="Delete all my NeetVerse data", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        deleted = self.bot.privacy_service.delete(self.user_id)
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        message = "Your profile and student records were deleted." if deleted else "No profile remained to delete."
        await interaction.response.edit_message(embed=embed("Data deleted", message, color=SUCCESS), view=self)
        self.stop()

    @discord.ui.button(label="Keep my data", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(embed=embed("Deletion cancelled", "Your data was not changed."), view=self)
        self.stop()


class MyDataGroup(app_commands.Group):
    def __init__(self, cog: "PrivacyCog") -> None:
        super().__init__(name="mydata", description="Export or delete your private NeetVerse records.")
        self.cog = cog

    @app_commands.command(name="export", description="Download your NeetVerse student data as JSON.")
    async def export(self, interaction: discord.Interaction) -> None:
        try:
            payload = self.cog.bot.privacy_service.export(str(interaction.user.id))
        except ValueError as exc:
            await reply(interaction, value=embed("Export unavailable", str(exc), color=ERROR))
            return
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        await interaction.response.send_message(
            content="Your private NeetVerse export:",
            file=discord.File(io.BytesIO(raw), filename=f"neetverse-{interaction.user.id}.json"),
            ephemeral=True,
        )

    @app_commands.command(name="delete", description="Permanently delete your profile and all student records.")
    async def delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=embed(
                "Delete all NeetVerse data?",
                "This permanently deletes your profile, study history, plans, goals, mocks, mistakes, mastery, and saved lectures. This cannot be undone.",
                color=ERROR,
            ),
            view=DeleteDataView(self.cog.bot, interaction.user.id),
            ephemeral=True,
        )


class PrivacyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = MyDataGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrivacyCog(bot))
