"""Trade system — cog & commands. UI/panel logic lives in trade_views.py."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.features.trade_views import (
    TradePanel,
    _panel_embed,
    _trade_root,
    _unlock,
    _history_embed_rows,
)
from bot.utils.checks import ensure_registered
from bot.utils.interaction_visibility import smart_reply
from bot.utils.squad_logic import get_player
from bot.utils.ui import make_embed

logger = logging.getLogger(__name__)


class TradesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active_trade_panels: dict[str, TradePanel] = {}
        self.trade_group = TradeGroup(self)
        self.bot.tree.add_command(self.trade_group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.trade_group.name, type=self.trade_group.type)

    def _load_trade_data(self) -> dict[str, Any]:
        data = self.bot.storage.load()
        return self.bot.trade_service.hydrate_json_trade_state(data)

    def register_panel(self, panel: TradePanel) -> None:
        self.active_trade_panels[panel.a_id] = panel
        self.active_trade_panels[panel.b_id] = panel

    def unregister_panel(self, panel: TradePanel) -> None:
        for user_id in (panel.a_id, panel.b_id):
            if self.active_trade_panels.get(user_id) is panel:
                self.active_trade_panels.pop(user_id, None)


class TradeGroup(app_commands.Group):
    def __init__(self, cog: "TradesCog") -> None:
        super().__init__(name="trade", description="Trade cards with other players.")
        self.cog = cog

    @app_commands.command(name="start", description="Start a trade negotiation with another player.")
    async def start(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return

        a_id = str(interaction.user.id)
        b_id = str(user.id)

        if a_id == b_id:
            await smart_reply(interaction, embed=make_embed(None, "❌ Invalid", "You can't trade with yourself."), ephemeral=True)
            return

        data = self.cog._load_trade_data()
        b_player = get_player(data, b_id)
        if not isinstance(b_player, dict):
            await smart_reply(interaction, embed=make_embed(None, "❌ Not Registered", f"{user.mention} hasn't registered yet."), ephemeral=True)
            return

        def _reserve_trade_pair(data: dict[str, Any]) -> tuple[bool, str]:
            pending = _trade_root(data).setdefault("pending", {})
            if self.cog.bot.trade_service.is_pending(a_id):
                return False, "You already have an active trade. Use `/trade cancel` first."
            if self.cog.bot.trade_service.is_pending(b_id):
                return False, f"{user.mention} already has an active trade."
            pending[a_id] = True
            pending[b_id] = True
            self.cog.bot.trade_service.add_pending_pair(a_id, b_id, mirror_json=False)
            return True, "ok"

        ok, msg = self.cog.bot.storage.with_lock(_reserve_trade_pair)
        if not ok:
            await smart_reply(interaction, embed=make_embed(None, "❌ Trade Active", msg), ephemeral=True)
            return

        a_name = str(interaction.user.display_name)
        b_name = str(user.display_name)

        panel = TradePanel(self.cog, a_id, b_id, a_name, b_name)
        self.cog.register_panel(panel)
        embed = _panel_embed(panel.session, False, False)

        if interaction.channel:
            sent = await interaction.channel.send(
                content=f"{user.mention} you've been invited to a trade by {interaction.user.mention}!",
                embed=embed,
                view=panel,
            )
            panel.message = sent

        await smart_reply(interaction, embed=make_embed(None, "✅ Trade Started", f"Trade panel opened with {user.mention}!"), ephemeral=True)

    @app_commands.command(name="cancel", description="Cancel your active trade session.")
    async def cancel(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return
        user_id = str(interaction.user.id)

        panel = self.cog.active_trade_panels.get(user_id)
        if panel is not None:
            def mutate(data: dict[str, Any]) -> None:
                for sid, key in ((panel.a_id, "a_card"), (panel.b_id, "b_card")):
                    card = panel.session.get(key)
                    if isinstance(card, dict):
                        player = get_player(data, sid)
                        if isinstance(player, dict):
                            _unlock(player.get("user", {}).get("inventory", []), str(card.get("uid", "")))
                pending = _trade_root(data).setdefault("pending", {})
                pending.pop(panel.a_id, None)
                pending.pop(panel.b_id, None)

            self.cog.bot.storage.with_lock(mutate)
            self.cog.bot.trade_service.remove_pending_pair(panel.a_id, panel.b_id, mirror_json=False)
            self.cog.unregister_panel(panel)
            panel.stop()
            if panel.message:
                try:
                    embed = make_embed(None, "LOOKISM HXCC • TRADE", f"╭─ 🚫 Trade Cancelled\n│ Cancelled by @{interaction.user.display_name}\n╰────────────────", color=0xE74C3C)
                    await panel.message.edit(embed=embed, view=None)
                except Exception:
                    logger.exception("Failed to edit cancelled trade panel message")
            await smart_reply(interaction, embed=make_embed(None, "✅ Cancelled", "Your trade session has been cancelled."), ephemeral=True)
            return

        ok = self.cog.bot.trade_service.remove_pending(user_id)
        if not ok:
            await smart_reply(interaction, embed=make_embed(None, "❌ No Trade", "You don't have an active trade."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(None, "✅ Cancelled", "Your trade session has been cancelled."), ephemeral=True)

    @app_commands.command(name="history", description="View your trade history.")
    async def history(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return
        rows = self.cog.bot.trade_service.history_for_user(str(interaction.user.id), limit=20)
        embed = _history_embed_rows(str(interaction.user.id), str(interaction.user.display_name), rows)
        await smart_reply(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradesCog(bot))
