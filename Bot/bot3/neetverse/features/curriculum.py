"""Discord syllabus tracker and controlled official-version import."""

from __future__ import annotations

import json

import discord
from discord import app_commands
from discord.ext import commands

from config import OWNER_IDS
from neetverse.curriculum import CurriculumError, PROGRESS_FIELDS
from neetverse.ui import ERROR, SUCCESS, embed


class SyllabusGroup(app_commands.Group):
    def __init__(self, cog: "CurriculumCog") -> None:
        super().__init__(name="syllabus", description="Track your target-year official NEET syllabus.")
        self.cog = cog

    @app_commands.command(name="summary", description="Show your progress on your target-year syllabus.")
    async def summary(self, interaction: discord.Interaction) -> None:
        try:
            result = self.cog.bot.curriculum_service.summary(str(interaction.user.id))
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Syllabus unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        lines = [
            f"**{row['subject_code'].title()}** — {float(row['completion'] or 0):.1f}% across {row['nodes']} tracked nodes"
            for row in result["subjects"]
        ]
        version = result["version"]
        await interaction.response.send_message(
            embed=embed(f"📚 {version['label']}", "\n".join(lines) or "No chapter/topic nodes were imported."), ephemeral=True
        )

    @app_commands.command(name="find", description="Find chapters or topics in your target-year syllabus.")
    async def find(self, interaction: discord.Interaction, query: str) -> None:
        try:
            rows = self.cog.bot.curriculum_service.find_nodes(str(interaction.user.id), query, limit=15)
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Syllabus unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        lines = [f"`{row['id'][:8]}` **{row['name']}** — {row['subject_code'].title()} / {row['node_type']}" for row in rows]
        await interaction.response.send_message(embed=embed("Syllabus search", "\n".join(lines) or "No matching nodes."), ephemeral=True)

    @app_commands.command(name="progress", description="Update one part of your own syllabus progress.")
    @app_commands.choices(progress_type=[app_commands.Choice(name=value.replace("_percent", "").title(), value=value) for value in sorted(PROGRESS_FIELDS)])
    async def progress(self, interaction: discord.Interaction, node_id: str, progress_type: app_commands.Choice[str], percent: app_commands.Range[float, 0, 100]) -> None:
        try:
            rows = self.cog.bot.curriculum_service.find_nodes(str(interaction.user.id), node_id, limit=20)
            exact = next((row for row in rows if row["id"] == node_id or row["id"].startswith(node_id)), None)
            if exact is None:
                raise CurriculumError("No syllabus node matches that ID")
            result = self.cog.bot.curriculum_service.update_progress(
                str(interaction.user.id), exact["id"], progress_type.value, float(percent)
            )
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Progress not updated", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embed("Syllabus progress saved", f"**{result['node_name']}** • {progress_type.name}: {percent}%", color=SUCCESS), ephemeral=True
        )

    @app_commands.command(name="import_version", description="Owner: import a reviewed official syllabus JSON file.")
    async def import_version(self, interaction: discord.Interaction, document: discord.Attachment, activate: bool = False) -> None:
        if int(interaction.user.id) not in OWNER_IDS:
            await interaction.response.send_message(embed=embed("Not allowed", "Only a configured NeetVerse owner can import official syllabus data.", color=ERROR), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if document.size > 2_000_000:
                raise CurriculumError("Syllabus JSON must be under 2 MB")
            payload = json.loads((await document.read()).decode("utf-8"))
            version_id = self.cog.bot.curriculum_service.import_version(payload, activate=activate)
        except (CurriculumError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            await interaction.followup.send(embed=embed("Import rejected", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.followup.send(
            embed=embed("Syllabus imported", f"Version `{version_id[:8]}` imported as {'active' if activate else 'draft'}.", color=SUCCESS), ephemeral=True
        )


class CurriculumCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = SyllabusGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CurriculumCog(bot))
