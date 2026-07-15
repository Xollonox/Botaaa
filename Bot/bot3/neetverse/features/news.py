"""Discord entry points for official NEET notices."""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import MISSING

from neetverse.ui import SUCCESS, WARNING, embed, status_icon


class NewsGroup(app_commands.Group):
    def __init__(self, cog: "NewsCog") -> None:
        super().__init__(name="news", description="Official NEET and counselling notices.")
        self.cog = cog

    @app_commands.command(name="latest", description="Show notices collected only from official authorities.")
    async def latest(self, interaction: discord.Interaction) -> None:
        items = self.cog.bot.news_service.latest(limit=8)
        if not items:
            await interaction.response.send_message(
                embed=embed(
                    "No official notices cached",
                    "📡 The authority monitor is waiting for its first successful source check.",
                    color=WARNING,
                ),
            )
            return
        lines = [
            f"📌 **[{item['title']}]({item['url']})**\n"
            f"└ 🏛️ `{item['source_name']}`"
            + (f" • <t:{item['published_at']}:R>" if item.get("published_at") else "")
            for item in items
        ]
        await interaction.response.send_message(
            embed=embed("📢  Official NEET Intelligence Feed", "\n\n".join(lines))
        )

    @app_commands.command(name="status", description="Show the health of official news sources.")
    async def status(self, interaction: discord.Interaction) -> None:
        rows = self.cog.bot.news_service.source_status()
        if not rows:
            description = "Sources have not been checked yet."
        else:
            description = "\n\n".join(
                f"{status_icon(row['status'])} **{row['source_key'].upper()}** • `{row['status'].upper()}`\n"
                f"└ `{row['item_count']} notices` • checked <t:{row['checked_at']}:R>"
                for row in rows
            )
        healthy = bool(rows) and all(row["status"] == "success" for row in rows)
        await interaction.response.send_message(
            embed=embed(
                "📡  Official Source Monitor",
                description,
                color=SUCCESS if healthy else WARNING,
            )
        )


class NewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = NewsGroup(self)
        self.bot.tree.add_command(self.group)

    async def cog_load(self) -> None:
        if getattr(self.bot, "_ready", MISSING) is not MISSING:
            self.news_poll.start()

    async def cog_unload(self) -> None:
        self.news_poll.cancel()
        self.bot.tree.remove_command(self.group.name, type=self.group.type)

    @tasks.loop(hours=6)
    async def news_poll(self) -> None:
        await self.bot.news_service.sync_all(now=int(time.time()))

    @news_poll.before_loop
    async def before_news_poll(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NewsCog(bot))
