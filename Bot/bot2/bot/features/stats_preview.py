"""Stats reference preview command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from bot.utils.interaction_visibility import smart_reply


STAT_DOC = Path(__file__).resolve().parents[4] / "docs" / "STATS.md"
PAGE_LIMIT = 3300


@dataclass(frozen=True)
class StatsPage:
    section: str
    title: str
    body: str


def _stats_doc_path() -> Path:
    return STAT_DOC


def _split_markdown_sections(markdown: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"
    current_lines: list[str] = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = line.removeprefix("## ").strip() or "Overview"
            current_lines = []
            continue
        if line.startswith("# ") or line.startswith("> "):
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))
    return sections


def _chunk_lines(lines: list[str], limit: int = PAGE_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        extra = len(line) + 1
        if current and current_len + extra > limit:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += extra

    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk] or ["No content found."]


def _format_markdown_preview(text: str) -> str:
    lines: list[str] = []
    in_table = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("|"):
            if not in_table:
                lines.append("```text")
                in_table = True
            lines.append(line[:180])
            continue
        if in_table:
            lines.append("```")
            in_table = False

        if line.startswith("### "):
            lines.append(f"**{line.removeprefix('### ').strip()}**")
        elif line.startswith("- "):
            lines.append(f"- {line.removeprefix('- ').strip()}")
        elif line:
            lines.append(line)
        else:
            lines.append("")

    if in_table:
        lines.append("```")
    return "\n".join(lines).strip()


def build_stats_pages(markdown: str) -> list[StatsPage]:
    pages: list[StatsPage] = []
    for section, lines in _split_markdown_sections(markdown):
        chunks = _chunk_lines(lines)
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            suffix = f" ({index}/{total})" if total > 1 else ""
            pages.append(
                StatsPage(
                    section=section,
                    title=f"{section}{suffix}",
                    body=_format_markdown_preview(chunk),
                )
            )
    return pages or [StatsPage(section="Overview", title="Overview", body="No stats reference found.")]


class StatsPreviewView(discord.ui.View):
    def __init__(self, invoker_id: int, pages: list[StatsPage], *, timeout: float = 180) -> None:
        super().__init__(timeout=timeout)
        self.invoker_id = int(invoker_id)
        self.pages = pages
        self.page = 0
        self.section_select.options = self._section_options()
        self._sync_controls()

    def _section_options(self) -> list[discord.SelectOption]:
        seen: set[str] = set()
        options: list[discord.SelectOption] = []
        for index, page in enumerate(self.pages):
            if page.section in seen:
                continue
            seen.add(page.section)
            options.append(discord.SelectOption(label=page.section[:100], value=str(index)))
            if len(options) >= 25:
                break
        return options

    def _sync_controls(self) -> None:
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= len(self.pages) - 1
        self.section_select.placeholder = self.pages[self.page].section[:100]

    async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.invoker_id:
            return True
        await interaction.response.send_message("This stats preview is not yours.", ephemeral=True)
        return False

    def build_embed(self) -> discord.Embed:
        page = self.pages[self.page]
        embed = discord.Embed(
            title="LOOKISM HXCC - Stats Reference",
            description=page.body[:4096],
            color=0xE11D48,
        )
        embed.add_field(name="Section", value=page.title[:1024], inline=True)
        embed.add_field(name="Page", value=f"{self.page + 1}/{len(self.pages)}", inline=True)
        embed.set_footer(text="Source: docs/STATS.md")
        return embed

    @discord.ui.select(placeholder="Jump to section", min_values=1, max_values=1, row=0)
    async def section_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if not await self._ensure_owner(interaction):
            return
        self.page = int(select.values[0])
        self._sync_controls()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._ensure_owner(interaction):
            return
        self.page = max(0, self.page - 1)
        self._sync_controls()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, row=1)
    async def next_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._ensure_owner(interaction):
            return
        self.page = min(len(self.pages) - 1, self.page + 1)
        self._sync_controls()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class StatsCog(commands.Cog):
    @commands.group(name="stats", invoke_without_subcommand=True)
    async def stats(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @stats.command(name="load")
    async def stats_load(self, ctx: commands.Context) -> None:
        path = _stats_doc_path()
        if not path.exists():
            await smart_reply(ctx, content="`docs/STATS.md` was not found.", ephemeral=True)
            return

        pages = build_stats_pages(path.read_text(encoding="utf-8"))
        view = StatsPreviewView(int(ctx.author.id), pages)
        await smart_reply(ctx, embed=view.build_embed(), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
