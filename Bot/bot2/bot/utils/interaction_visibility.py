from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from bot.utils.ui import skin_embed, style_view

logger = logging.getLogger(__name__)


def _is_owner_command(obj: Any) -> bool:
    command = getattr(obj, "command", None)
    cmd_name = getattr(command, "name", "") if command is not None else ""
    return str(cmd_name).startswith("o_")


def _load_data(obj: Any) -> dict[str, Any] | None:
    # Works for both Interaction (obj.client) and Context (obj.bot)
    client = getattr(obj, "client", None) or getattr(obj, "bot", None)
    storage = getattr(client, "storage", None)
    if storage is None:
        return None
    try:
        payload = storage.load_readonly()
        return payload if isinstance(payload, dict) else None
    except Exception:
        logger.exception("Unexpected error loading storage data for interaction styling")
        return None


def _style_payload(kwargs: dict[str, Any], obj: Any) -> None:
    data = _load_data(obj)

    embed = kwargs.get("embed")
    if embed is not None:
        kwargs["embed"] = skin_embed(embed, obj, data)

    embeds = kwargs.get("embeds")
    if isinstance(embeds, list):
        kwargs["embeds"] = [skin_embed(item, obj, data) for item in embeds]

    view = kwargs.get("view")
    if view is not None:
        kwargs["view"] = style_view(view, data)


async def smart_reply(ctx_or_interaction: Any, *args: Any, **kwargs: Any) -> Any:
    _style_payload(kwargs, ctx_or_interaction)

    # Prefix command (commands.Context) — no ephemeral support, always send to channel
    if not hasattr(ctx_or_interaction, "response"):
        kwargs.pop("ephemeral", None)
        return await ctx_or_interaction.send(*args, **kwargs)

    # Slash command (discord.Interaction) — legacy path
    if "ephemeral" not in kwargs:
        kwargs["ephemeral"] = False

    if ctx_or_interaction.response.is_done():
        return await ctx_or_interaction.followup.send(*args, **kwargs)
    return await ctx_or_interaction.response.send_message(*args, **kwargs)


async def error_reply(ctx_or_interaction: Any, *args: Any, **kwargs: Any) -> None:
    """Send an error/warning message that auto-deletes after 2 seconds."""
    import asyncio

    _style_payload(kwargs, ctx_or_interaction)

    # Prefix command path
    if not hasattr(ctx_or_interaction, "response"):
        kwargs.pop("ephemeral", None)
        try:
            msg = await ctx_or_interaction.send(*args, **kwargs)
            await asyncio.sleep(2)
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            logger.exception("Discord HTTP error sending error_reply")
        return

    # Slash command path (legacy)
    kwargs.pop("ephemeral", None)
    kwargs["ephemeral"] = False

    try:
        if ctx_or_interaction.response.is_done():
            msg = await ctx_or_interaction.followup.send(*args, **kwargs, wait=True)
        else:
            await ctx_or_interaction.response.send_message(*args, **kwargs)
            try:
                msg = await ctx_or_interaction.original_response()
            except discord.HTTPException:
                return
        if msg:
            await asyncio.sleep(2)
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
    except discord.HTTPException:
        logger.exception("Discord HTTP error sending error_reply")
