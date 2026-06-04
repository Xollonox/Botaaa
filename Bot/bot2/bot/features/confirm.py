"""Global confirm command for previously staged dangerous actions."""

from __future__ import annotations

from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.confirm_pipeline import pop_and_validate_action
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply

ConfirmHandler = Callable[[dict[str, Any], dict[str, Any]], tuple[bool, str]]


def _noop_handler(_: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    return True, f"Confirmed `{payload.get('action_name', 'action')}`."


CONFIRM_HANDLERS: dict[str, ConfirmHandler] = {
    "noop": _noop_handler,
}


class ConfirmCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="confirm", description="Confirm a pending action by action ID.")
    async def confirm(self, interaction: discord.Interaction, action_id: str) -> None:
        ts = now_ts()
        owner_id = str(interaction.user.id)

        def mutate(d: dict[str, Any]):
            ok, result = pop_and_validate_action(d, owner_id, action_id, ts)
            if not ok:
                return False, str(result)
            action = result if isinstance(result, dict) else {}
            action_type = str(action.get("action_type", ""))
            payload = action.get("payload", {}) if isinstance(action.get("payload"), dict) else {}
            handler = CONFIRM_HANDLERS.get(action_type)
            if handler is None:
                return False, "unknown_action_type"
            h_ok, h_msg = handler(d, payload)
            if not h_ok:
                return False, h_msg
            return True, h_msg

        ok, msg = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, 
                embed=make_embed(data, f"{e('warning', data)} Confirm Failed", str(msg)),
                ephemeral=True,
            )
            return
        await smart_reply(interaction, 
            embed=make_embed(data, f"{e('ok', data)} Confirmed", str(msg)),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfirmCog(bot))
