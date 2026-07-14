"""Permission check helpers for Discord interactions."""

from __future__ import annotations

import os
from typing import Any

import discord
from discord.ext import commands

from bot import config as _config
from bot.utils.interaction_visibility import smart_reply


def effective_owner_ids() -> set[int]:
    """Return configured bot owner IDs from environment.

    Reads OWNER_IDS from bot.config dynamically so tests that reload the
    config module (or runtime env changes) are picked up.
    """
    return _config.OWNER_IDS


def is_owner(interaction: discord.Interaction) -> bool:
    """Return True if the interaction user is a bot owner."""
    return interaction.user.id in effective_owner_ids()


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
    # Read-only fast path: ensure_registered only inspects players/user_row.
    data = storage.load_readonly()

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
        if isinstance(user_row, dict) and bool(user_row.get("is_muted", False)):
            mute_reason = str(user_row.get("mute_reason", "No reason provided."))
            embed = make_embed(
                data,
                f"{e('no', data)} You Are Muted",
                f"You cannot use bot commands right now.\n**Reason:** {mute_reason}",
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
