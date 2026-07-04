import asyncio
import logging
from typing import Optional

import discord
from discord.ext import commands

from config import DISCORD_TOKEN, LOG_LEVEL, assert_runtime_config
from http_client import close_session
import memory as _memory

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

BOT_MEMORY = _memory.BOT_MEMORY
BOT_SETTINGS = _memory.BOT_SETTINGS
_save_json_file_async = _memory._save_json_file_async


async def remember_line(
    user_id: int,
    prefix: str,
    line: str,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> None:
    """Wrapper for tests that patch main.BOT_MEMORY, _save_json_file_async, BOT_SETTINGS.

    The assignments below are no-ops functionally (both sides reference the same objects),
    but they're retained because tests in test_remember_line.py patch these module attributes
    with mock objects. Without these lines, the patches wouldn't affect _memory's use.
    """
    _memory.BOT_MEMORY = BOT_MEMORY
    _memory.BOT_SETTINGS = BOT_SETTINGS
    _memory._save_json_file_async = _save_json_file_async
    await _memory.remember_line(
        user_id,
        prefix,
        line,
        guild_id=guild_id,
        channel_id=channel_id,
    )


async def main() -> None:
    assert_runtime_config()
    try:
        async with bot:
            await bot.load_extension("commands")
            await bot.load_extension("events")
            await bot.start(DISCORD_TOKEN)
    finally:
        await close_session()


if __name__ == "__main__":
    asyncio.run(main())
