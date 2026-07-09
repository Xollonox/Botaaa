"""Server-level rule enforcement helpers."""

from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands


def _get_user(obj: Any) -> discord.User | discord.Member | None:
    return getattr(obj, "user", None) or getattr(obj, "author", None)


def _get_bot(obj: Any) -> commands.Bot | None:
    return getattr(obj, "client", None) or getattr(obj, "bot", None)


def _get_channel_id(obj: Any) -> int:
    channel = getattr(obj, "channel", None)
    if channel is not None:
        return int(getattr(channel, "id", 0))
    return int(getattr(obj, "channel_id", 0))


def is_admin(obj: Any) -> bool:
    """Return True if the user has Administrator permission.

    Accepts both discord.Interaction and commands.Context.
    """
    from bot.utils.checks import is_owner
    if is_owner(obj):
        return True
    user = _get_user(obj)
    if user is None:
        return False
    if hasattr(user, "guild_permissions"):
        return bool(user.guild_permissions.administrator)  # type: ignore[union-attr]
    return False


def check_single_mode_allowed(
    obj: Any,
) -> tuple[bool, str, int]:
    """Check if the command is allowed under the current server mode.

    Accepts both discord.Interaction and commands.Context.

    Returns (allowed, mode, redirect_channel_id).
    """
    bot = _get_bot(obj)
    storage = getattr(bot, "storage", None) if bot is not None else None
    if storage is None:
        return True, "all", 0

    data = storage.load_readonly()
    settings = data.get("server_settings", {})
    if not isinstance(settings, dict):
        return True, "all", 0

    mode = str(settings.get("mode", "all"))
    if mode != "single":
        return True, mode, 0

    locked_id = int(settings.get("locked_channel_id", 0) or 0)
    if locked_id == 0:
        return True, mode, 0

    channel_id = _get_channel_id(obj)
    if channel_id == locked_id:
        return True, mode, locked_id

    return False, mode, locked_id


def check_battle_channel_allowed(
    obj: Any,
) -> tuple[bool, str | None, int | None]:
    """Check if the command channel is allowed for battle commands.

    Accepts both discord.Interaction and commands.Context.

    Returns (allowed, reason, battle_channel_id).
    """
    bot = _get_bot(obj)
    storage = getattr(bot, "storage", None) if bot is not None else None
    if storage is None:
        return True, None, None

    data = storage.load_readonly()
    settings = data.get("server_settings", {})
    if not isinstance(settings, dict):
        return True, None, None

    battle_id = int(settings.get("battle_channel_id", 0) or 0)
    if battle_id == 0:
        return True, None, None

    channel_id = _get_channel_id(obj)
    if channel_id == battle_id:
        return True, None, battle_id
    return False, "not_allowed", battle_id
