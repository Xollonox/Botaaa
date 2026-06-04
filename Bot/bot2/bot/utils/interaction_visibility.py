from __future__ import annotations

from typing import Any

from bot.utils.ui import skin_embed, style_view


def _is_owner_command(interaction: Any) -> bool:
    command = getattr(interaction, "command", None)
    cmd_name = getattr(command, "name", "") if command is not None else ""
    return str(cmd_name).startswith("o_")


def _load_data(interaction: Any) -> dict[str, Any] | None:
    client = getattr(interaction, "client", None)
    storage = getattr(client, "storage", None)
    if storage is None:
        return None
    try:
        payload = storage.load()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _style_payload(kwargs: dict[str, Any], interaction: Any) -> None:
    data = _load_data(interaction)

    embed = kwargs.get("embed")
    if embed is not None:
        kwargs["embed"] = skin_embed(embed, interaction, data)

    embeds = kwargs.get("embeds")
    if isinstance(embeds, list):
        kwargs["embeds"] = [skin_embed(item, interaction, data) for item in embeds]

    view = kwargs.get("view")
    if view is not None:
        kwargs["view"] = style_view(view, data)


async def smart_reply(interaction: Any, *args: Any, **kwargs: Any) -> Any:
    # Respect explicit visibility from the caller; otherwise keep the historical command-based default.
    if "ephemeral" not in kwargs:
        kwargs["ephemeral"] = False  # owner commands visible to all by default

    _style_payload(kwargs, interaction)

    if interaction.response.is_done():
        return await interaction.followup.send(*args, **kwargs)
    return await interaction.response.send_message(*args, **kwargs)


async def error_reply(interaction: Any, *args: Any, **kwargs: Any) -> None:
    """Send an error/warning message that auto-deletes after 2 seconds."""
    import asyncio
    kwargs.pop("ephemeral", None)
    kwargs["ephemeral"] = False  # must be non-ephemeral for delete_after to work

    _style_payload(kwargs, interaction)

    try:
        if interaction.response.is_done():
            msg = await interaction.followup.send(*args, **kwargs, wait=True)
        else:
            await interaction.response.send_message(*args, **kwargs)
            try:
                msg = await interaction.original_response()
            except Exception:
                return
        if msg:
            await asyncio.sleep(2)
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception:
        pass
