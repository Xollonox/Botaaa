"""Discord presentation helpers kept separate from academic rules."""

from __future__ import annotations

import discord


BRAND = 0x6C5CE7
SUCCESS = 0x2ECC71
WARNING = 0xF1C40F
ERROR = 0xE74C3C


def embed(title: str, description: str, *, color: int = BRAND) -> discord.Embed:
    value = discord.Embed(title=title[:256], description=description[:4096], color=color)
    value.set_footer(text="NeetVerse • Study with intention")
    return value


async def reply(interaction: discord.Interaction, *, content: str | None = None, value: discord.Embed | None = None, view: discord.ui.View | None = None) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=value, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(content=content, embed=value, view=view, ephemeral=True)


def duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
