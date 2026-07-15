"""Background processor for persisted domain events."""

from __future__ import annotations

import logging

from discord.ext import commands, tasks
from discord.utils import MISSING


logger = logging.getLogger(__name__)


class AutomationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        if getattr(self.bot, "_ready", MISSING) is not MISSING:
            self.process_events.start()

    def cog_unload(self) -> None:
        self.process_events.cancel()

    @tasks.loop(seconds=10)
    async def process_events(self) -> None:
        result = self.bot.event_processor.process_pending(limit=100)
        if result["failed"]:
            logger.warning("Domain event processing paused after a failed event")

    @process_events.before_loop
    async def before_processing(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomationCog(bot))
