"""Public, bounded web-search entry points."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from neetverse.ui import ERROR, embed
from neetverse.websearch import SearchRateLimitError, WebSearchError


SCOPE_CHOICES = [
    app_commands.Choice(name="Official authorities", value="official"),
    app_commands.Choice(name="Study sources", value="study"),
    app_commands.Choice(name="General web (use carefully)", value="web"),
]


class SearchGroup(app_commands.Group):
    def __init__(self, cog: "SearchCog") -> None:
        super().__init__(name="search", description="Find trusted study resources with a low-volume web search.")
        self.cog = cog

    @app_commands.command(name="web", description="Search official, study, or general web sources.")
    @app_commands.choices(scope=SCOPE_CHOICES)
    async def web(
        self,
        interaction: discord.Interaction,
        query: str,
        scope: app_commands.Choice[str],
        max_results: app_commands.Range[int, 1, 8] = 5,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            rows = await self.cog.bot.web_search_service.search(
                str(interaction.user.id), query, scope=scope.value, max_results=int(max_results)
            )
        except (SearchRateLimitError, WebSearchError) as exc:
            await interaction.followup.send(
                embed=embed("Web search unavailable", str(exc), color=ERROR), ephemeral=True
            )
            return
        if not rows:
            await interaction.followup.send(
                embed=embed(
                    "No trusted results",
                    "Try a broader query or switch from **Official** to **Study sources**.",
                ),
                ephemeral=True,
            )
            return
        lines = []
        for index, row in enumerate(rows, 1):
            title = discord.utils.escape_mentions(discord.utils.escape_markdown(row["title"]))
            snippet = discord.utils.escape_mentions(
                discord.utils.escape_markdown(row["snippet"] or "No preview available")
            )
            lines.append(f"**{index}. [{title}]({row['url']})**\n`{row['domain']}` • {snippet[:300]}")
        value = embed(
            f"🔎  Web Search • {scope.name}",
            "\n\n".join(lines) + "\n\n_Results are best-effort links, not verified academic advice._",
        )
        await interaction.followup.send(embed=value, ephemeral=False)


class SearchCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = SearchGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name, type=self.group.type)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
