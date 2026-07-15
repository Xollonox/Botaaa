"""Discord syllabus browser, progress tracker, and controlled version import."""

from __future__ import annotations

import json
import math

import discord
from discord import app_commands
from discord.ext import commands

from config import OWNER_IDS
from neetverse.curriculum import CurriculumError, PROGRESS_FIELDS
from neetverse.ui import ERROR, SUCCESS, embed, progress_bar, subject_icon


SUBJECT_CHOICES = [
    app_commands.Choice(name="⚛️ Physics", value="physics"),
    app_commands.Choice(name="🧪 Chemistry", value="chemistry"),
    app_commands.Choice(name="🧬 Biology", value="biology"),
]


class SyllabusNodeSelect(discord.ui.Select):
    def __init__(self, view: "SyllabusBrowserView", rows: list[dict]) -> None:
        options = [
            discord.SelectOption(
                label=str(row["name"])[:100],
                value=str(row["id"]),
                emoji=subject_icon(str(row["subject_code"])),
                description=(
                    f"{row['node_type'].title()} • {row['completion']:.0f}% complete"
                    + (" • open" if row["has_children"] else " • details")
                )[:100],
            )
            for row in rows
        ]
        super().__init__(placeholder="📂 Open a topic or subtopic…", options=options, row=0)
        self.browser = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.browser.history.append(self.browser.parent_token)
        self.browser.parent_token = self.values[0]
        self.browser.page = 0
        await self.browser.refresh(interaction)


class SyllabusBrowserView(discord.ui.View):
    PAGE_SIZE = 10

    def __init__(self, service, user_id: str, subject: str) -> None:
        super().__init__(timeout=300)
        self.service = service
        self.user_id = user_id
        self.subject = subject
        self.parent_token: str | None = None
        self.history: list[str | None] = []
        self.page = 0
        self.message: discord.Message | None = None
        self.result: dict = {}
        self.visible_rows: list[dict] = []
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        self.result = self.service.browse_nodes(
            self.user_id,
            subject=self.subject if self.parent_token is None else None,
            parent_token=self.parent_token,
        )
        rows = self.result["nodes"]
        pages = max(1, math.ceil(len(rows) / self.PAGE_SIZE))
        self.page = max(0, min(self.page, pages - 1))
        start = self.page * self.PAGE_SIZE
        self.visible_rows = rows[start:start + self.PAGE_SIZE]
        if self.visible_rows:
            self.add_item(SyllabusNodeSelect(self, self.visible_rows))

        back = discord.ui.Button(
            label="Back", emoji="↩️", style=discord.ButtonStyle.secondary,
            disabled=not self.history, row=1,
        )
        previous = discord.ui.Button(
            label="Previous", emoji="◀️", style=discord.ButtonStyle.primary,
            disabled=self.page == 0, row=1,
        )
        indicator = discord.ui.Button(
            label=f"{self.page + 1}/{pages}", style=discord.ButtonStyle.secondary,
            disabled=True, row=1,
        )
        next_button = discord.ui.Button(
            label="Next", emoji="▶️", style=discord.ButtonStyle.primary,
            disabled=self.page >= pages - 1, row=1,
        )

        async def go_back(interaction: discord.Interaction) -> None:
            self.parent_token = self.history.pop()
            self.page = 0
            await self.refresh(interaction)

        async def go_previous(interaction: discord.Interaction) -> None:
            self.page -= 1
            await self.refresh(interaction)

        async def go_next(interaction: discord.Interaction) -> None:
            self.page += 1
            await self.refresh(interaction)

        back.callback = go_back
        previous.callback = go_previous
        next_button.callback = go_next
        self.add_item(back)
        self.add_item(previous)
        self.add_item(indicator)
        self.add_item(next_button)
        source = str(self.result["version"].get("source_url") or "")
        if source:
            self.add_item(
                discord.ui.Button(
                    label="Official PDF", emoji="🔗", url=source,
                    style=discord.ButtonStyle.link, row=2,
                )
            )

    def current_embed(self) -> discord.Embed:
        version = self.result["version"]
        parent = self.result["parent"]
        rows = self.visible_rows
        if rows:
            lines = [
                f"{subject_icon(row['subject_code'])} `{row['id'][:8]}` **{row['name']}**\n"
                f"└ `{row['node_type'].upper()}` • `{row['leaf_count']} leaf nodes` • "
                f"{progress_bar(row['completion'], 100, width=7)}"
                for row in rows
            ]
            description = (
                f"📜 **{version['label']}**  •  `OFFICIAL REFERENCE`\n"
                f"📂 **{parent['name'] if parent else self.subject.title()}**\n\n"
                + "\n\n".join(lines)
                + "\n\n_Select an item to drill down. Completion is calculated from leaf subtopics._"
            )
        elif parent:
            axes = [
                ("Lecture", parent.get("lecture_percent") or 0),
                ("Reading", parent.get("reading_percent") or 0),
                ("Notes", parent.get("notes_percent") or 0),
                ("Practice", parent.get("practice_percent") or 0),
                ("PYQ", parent.get("pyq_percent") or 0),
            ]
            description = (
                f"{subject_icon(parent['subject_code'])} **{parent['name']}**\n"
                f"`{parent['node_type'].upper()}` • ID `{parent['id'][:8]}`\n\n"
                + "\n".join(
                    f"**{name}** {progress_bar(value, 100, width=8)}" for name, value in axes
                )
                + "\n\n_This is a leaf subtopic. Use `/syllabus progress` with its ID to update a track._"
            )
        else:
            description = "No nodes are available for this subject."
        value = embed(f"📚  {self.subject.title()} • Syllabus Navigator", description)
        value.url = str(version.get("source_url") or "") or None
        return value

    async def refresh(self, interaction: discord.Interaction) -> None:
        try:
            self._rebuild()
        except CurriculumError as exc:
            await interaction.response.send_message(
                embed=embed("Syllabus unavailable", str(exc), color=ERROR), ephemeral=True
            )
            return
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button) or item.style != discord.ButtonStyle.link:
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class SyllabusGroup(app_commands.Group):
    def __init__(self, cog: "CurriculumCog") -> None:
        super().__init__(name="syllabus", description="Browse and track the official NEET syllabus.")
        self.cog = cog

    @app_commands.command(name="summary", description="Post automatically calculated syllabus completion.")
    async def summary(self, interaction: discord.Interaction) -> None:
        try:
            result = self.cog.bot.curriculum_service.summary(str(interaction.user.id))
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Syllabus unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        lines = [
            f"{subject_icon(row['subject_code'])} **{row['subject_code'].title()}** • `{row['nodes']} subtopics`\n"
            f"└ {progress_bar(float(row['completion'] or 0), 100, width=11)}"
            for row in result["subjects"]
        ]
        version = result["version"]
        total_nodes = sum(int(row["nodes"]) for row in result["subjects"])
        overall = (
            sum(float(row["completion"] or 0) * int(row["nodes"]) for row in result["subjects"]) / total_nodes
            if total_nodes else 0
        )
        value = embed(
            f"📚  {version['label']} • Syllabus HUD",
            f"🎯 **TOTAL COMPLETION** {progress_bar(overall, 100, width=14)}\n\n"
            + ("\n\n".join(lines) or "No leaf subtopics were imported."),
        )
        value.url = str(version.get("source_url") or "") or None
        await interaction.response.send_message(embed=value, ephemeral=False)

    @app_commands.command(name="versions", description="List available reviewed official syllabus versions.")
    async def versions(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.curriculum_service.list_versions()
        lines = [
            f"📜 `{row['id'][:8]}` **{row['label']}**\n"
            f"└ `{row['node_count']} nodes` • [official source]({row['source_url']})"
            for row in rows
        ]
        await interaction.response.send_message(
            embed=embed(
                "📚  Official Syllabus Vault",
                "\n\n".join(lines) or "No reviewed syllabus version is available.",
            ),
            ephemeral=False,
        )

    @app_commands.command(name="use", description="Select which official syllabus version your profile tracks.")
    async def use(self, interaction: discord.Interaction, version_id: str) -> None:
        try:
            version = self.cog.bot.curriculum_service.select_version(str(interaction.user.id), version_id)
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Syllabus not selected", str(exc), color=ERROR), ephemeral=True)
            return
        profile = self.cog.bot.profile_service.get(str(interaction.user.id)) or {}
        note = ""
        if profile.get("target_year") != version["target_year"]:
            note = (
                f"\n\n⚠️ Your target is **NEET {profile.get('target_year') or 'unset'}**. "
                f"This is the official **{version['target_year']} reference**, not a claimed {profile.get('target_year')} release."
            )
        await interaction.response.send_message(
            embed=embed("Syllabus selected", f"Now tracking **{version['label']}**.{note}", color=SUCCESS),
            ephemeral=True,
        )

    @app_commands.command(name="browse", description="Browse every official unit, topic and subtopic.")
    @app_commands.choices(subject=SUBJECT_CHOICES)
    async def browse(self, interaction: discord.Interaction, subject: app_commands.Choice[str]) -> None:
        try:
            view = SyllabusBrowserView(
                self.cog.bot.curriculum_service,
                str(interaction.user.id),
                subject.value,
            )
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Syllabus unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=False)
        view.message = await interaction.original_response()

    @app_commands.command(name="find", description="Find units, topics or subtopics in your selected syllabus.")
    async def find(self, interaction: discord.Interaction, query: str) -> None:
        try:
            rows = self.cog.bot.curriculum_service.find_nodes(str(interaction.user.id), query, limit=15)
        except CurriculumError as exc:
            await interaction.response.send_message(embed=embed("Syllabus unavailable", str(exc), color=ERROR), ephemeral=True)
            return
        lines = [
            f"{subject_icon(row['subject_code'])} `{row['id'][:8]}` **{row['name']}**\n"
            f"└ `{row['subject_code'].upper()}` • `{row['node_type'].upper()}`"
            for row in rows
        ]
        await interaction.response.send_message(embed=embed("Syllabus search", "\n\n".join(lines) or "No matching nodes."), ephemeral=False)

    @app_commands.command(name="progress", description="Update a syllabus track; parent changes roll down to subtopics.")
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
            embed=embed(
                "Syllabus progress saved",
                f"📚 **{result['node_name']}**\n"
                f"{progress_bar(percent, 100, width=12)}\n"
                f"**{progress_type.name}** updated across `{result['affected_nodes']}` leaf subtopic(s).",
                color=SUCCESS,
            ), ephemeral=True
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
