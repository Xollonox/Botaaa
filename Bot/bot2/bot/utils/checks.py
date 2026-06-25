"""Permission check helpers for Discord interactions."""

from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from bot.config import OWNER_IDS
from bot.utils.interaction_visibility import smart_reply


def is_owner(interaction: discord.Interaction) -> bool:
    """Return True if the interaction user is a bot owner."""
    return interaction.user.id in OWNER_IDS


def is_registered(data: dict[str, Any], user_id: str) -> bool:
    """Return True if *user_id* has a player record in *data*."""
    players = data.get("players", {})
    return isinstance(players, dict) and str(user_id) in players


async def ensure_registered(
    interaction: discord.Interaction,
    storage: Any,
) -> bool:
    """
    Check if the interacting user is registered.
    If not, send an ephemeral error message and return False.
    """
    from bot.utils.ui import e, make_embed

    user_id = str(interaction.user.id)
    data = storage.load()

    if is_registered(data, user_id):
        # Block banned users from all bot commands
        player = data.get("players", {}).get(user_id, {})
        user_row = player.get("user", {}) if isinstance(player, dict) else {}
        if isinstance(user_row, dict) and bool(user_row.get("is_banned", False)):
            from bot.utils.ui import e, make_embed
            ban_reason = str(user_row.get("ban_reason", "No reason provided."))
            embed = make_embed(
                data,
                f"{e('no', data)} You Are Banned",
                f"You have been banned from using this bot.\n**Reason:** {ban_reason}",
            )
            await smart_reply(interaction, embed=embed, ephemeral=True)
            return False
        return True

    embed = make_embed(
        data,
        f"{e('warning', data)} Not Registered",
        "You need to run `/start` to register your account first.",
    )
    if interaction.response.is_done():
        await smart_reply(interaction, embed=embed, ephemeral=True)
    else:
        await smart_reply(interaction, embed=embed, ephemeral=True)
    return False
