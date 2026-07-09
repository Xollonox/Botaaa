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


def is_owner(obj: Any) -> bool:
    """Return True if the user is a bot owner.

    Accepts both discord.Interaction and commands.Context.
    """
    user = getattr(obj, "user", None) or getattr(obj, "author", None)
    if user is None:
        return False
    return user.id in effective_owner_ids()


def is_registered(data: dict[str, Any], user_id: str) -> bool:
    """Return True if *user_id* has a player record in *data*."""
    players = data.get("players", {})
    return isinstance(players, dict) and str(user_id) in players


async def ensure_registered(
    obj: Any,
    storage: Any,
) -> bool:
    """Check if the user is registered.

    Accepts both discord.Interaction and commands.Context.
    If not registered, sends an error and returns False.
    """
    from bot.utils.ui import e, make_embed

    user = getattr(obj, "user", None) or getattr(obj, "author", None)
    if user is None:
        return False
    user_id = str(user.id)
    data = storage.load_readonly()

    if is_registered(data, user_id):
        player = data.get("players", {}).get(user_id, {})
        user_row = player.get("user", {}) if isinstance(player, dict) else {}
        if isinstance(user_row, dict) and bool(user_row.get("is_banned", False)):
            ban_reason = str(user_row.get("ban_reason", "No reason provided."))
            embed = make_embed(
                data,
                f"{e('no', data)} You Are Banned",
                f"You have been banned from using this bot.\n**Reason:** {ban_reason}",
            )
            await smart_reply(obj, embed=embed, ephemeral=True)
            return False
        return True

    embed = make_embed(
        data,
        f"{e('warning', data)} Not Registered",
        "You need to run `!start` to register your account first.",
    )
    await smart_reply(obj, embed=embed, ephemeral=True)
    return False
