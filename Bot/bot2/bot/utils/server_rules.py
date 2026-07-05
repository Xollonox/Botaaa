"""Server-level rule enforcement helpers."""

from __future__ import annotations

from typing import Any

import discord


def is_admin(interaction: discord.Interaction) -> bool:
    """Return True if the interaction user has Administrator permission."""
    from bot.utils.checks import is_owner
    if is_owner(interaction):
        return True
    member = interaction.user
    if hasattr(member, "guild_permissions"):
        return bool(member.guild_permissions.administrator)  # type: ignore[union-attr]
    return False


def check_single_mode_allowed(
    interaction: discord.Interaction,
) -> tuple[bool, str, int]:
    """
    Check whether the interaction is allowed under the current server mode.

    Returns (allowed, mode, redirect_channel_id).
    - If mode is "all" or no mode is configured, allowed=True.
    - If mode is "single", allowed=True only when the interaction channel
      matches the locked_channel_id.
    """
    bot = interaction.client
    storage = getattr(bot, "storage", None)
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

    channel_id = interaction.channel_id or 0
    if int(channel_id) == locked_id:
        return True, mode, locked_id

    return False, mode, locked_id


def check_battle_channel_allowed(
    interaction: discord.Interaction,
) -> tuple[bool, str | None, int | None]:
    """
    Check whether the interaction channel is allowed for battle commands.

    Returns (allowed, reason, battle_channel_id).
    If battle_channel_id is None/0, any channel is allowed.
    """
    bot = interaction.client
    storage = getattr(bot, "storage", None)
    if storage is None:
        return True, None, None

    data = storage.load_readonly()
    settings = data.get("server_settings", {})
    if not isinstance(settings, dict):
        return True, None, None

    battle_id = int(settings.get("battle_channel_id", 0) or 0)
    if battle_id == 0:
        return True, None, None

    channel_id = int(interaction.channel_id or 0)
    if channel_id == battle_id:
        return True, None, battle_id
    return False, "not_allowed", battle_id
