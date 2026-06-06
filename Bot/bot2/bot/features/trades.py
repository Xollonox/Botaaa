"""Trade system — cog & commands. UI/panel logic lives in trade_views.py."""

from __future__ import annotations

import logging
import time
import uuid
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

    async def _load_trade_data(self) -> dict[str, Any]:
        data = self.bot.storage.load()
        return await self.bot.trade_service.hydrate_json_trade_state(data)

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

        data = await self.cog._load_trade_data()
        b_player = get_player(data, b_id)
        if not isinstance(b_player, dict):
            await smart_reply(interaction, embed=make_embed(None, "❌ Not Registered", f"{user.mention} hasn't registered yet."), ephemeral=True)
            return

        # Attempt the SQLite insert atomically first (INSERT OR IGNORE).
        # add_pending_pair returns False if either user is already pending,
        # preventing a TOCTOU race between the is_pending check and the write.
        inserted = await self.cog.bot.trade_service.add_pending_pair(a_id, b_id, mirror_json=False)
        if not inserted:
            # Determine which user is already pending for a useful error message.
            if await self.cog.bot.trade_service.is_pending(a_id):
                msg = "You already have an active trade. Use `/trade cancel` first."
            else:
                msg = f"{user.mention} already has an active trade."
            await smart_reply(interaction, embed=make_embed(None, "❌ Trade Active", msg), ephemeral=True)
            return

        # SQLite insert succeeded — now mirror into JSON under the storage lock.
        def _mirror_pending(data: dict[str, Any]) -> None:
            pending = _trade_root(data).setdefault("pending", {})
            pending[a_id] = True
            pending[b_id] = True

        try:
            self.cog.bot.storage.with_lock(_mirror_pending)
        except Exception:
            # JSON mutation failed — roll back the SQLite insert so state is consistent.
            await self.cog.bot.trade_service.remove_pending_pair(a_id, b_id, mirror_json=False)
            raise

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
            await self.cog.bot.trade_service.remove_pending_pair(panel.a_id, panel.b_id, mirror_json=False)
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

        ok = await self.cog.bot.trade_service.remove_pending(user_id)
        if not ok:
            await smart_reply(interaction, embed=make_embed(None, "❌ No Trade", "You don't have an active trade."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(None, "✅ Cancelled", "Your trade session has been cancelled."), ephemeral=True)

    @app_commands.command(name="history", description="View your trade history.")
    async def history(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return
        rows = await self.cog.bot.trade_service.history_for_user(str(interaction.user.id), limit=20)
        embed = _history_embed_rows(str(interaction.user.id), str(interaction.user.display_name), rows)
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="post", description="Post a trade offer: I have X, I want Y.")
    @app_commands.describe(have_card="Card you're offering", want_card="Card you want in return")
    async def post(self, interaction: discord.Interaction, have_card: str, want_card: str) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return

        user_id = str(interaction.user.id)
        data = await self.cog._load_trade_data()
        player = get_player(data, user_id)
        if not isinstance(player, dict):
            await smart_reply(interaction, embed=make_embed(None, "❌ Error", "Player data not found."), ephemeral=True)
            return

        inventory = player.get("user", {}).get("inventory", [])
        if not isinstance(inventory, list):
            inventory = []

        have_item = None
        for item in inventory:
            if isinstance(item, dict) and str(item.get("name", "")).lower() == have_card.lower() and not item.get("trade_locked"):
                have_item = item
                break

        if not have_item:
            await smart_reply(
                interaction,
                embed=make_embed(None, "❌ Card Not Available", f"You don't have '{have_card}' available to trade."),
                ephemeral=True,
            )
            return

        item_uid = str(have_item.get("uid", ""))
        offer_id = str(uuid.uuid4())[:8]
        now = int(time.time())
        expires_at = now + 172800

        def lock_card(data: dict[str, Any]) -> None:
            player = get_player(data, user_id)
            if isinstance(player, dict):
                inventory = player.get("user", {}).get("inventory", [])
                if isinstance(inventory, list):
                    for item in inventory:
                        if isinstance(item, dict) and str(item.get("uid", "")) == item_uid:
                            item["trade_locked"] = True
                            break

        self.cog.bot.storage.with_lock(lock_card)
        await self.cog.bot.trade_service.post_offer(offer_id, user_id, str(interaction.user.display_name), have_card, want_card, item_uid, now, expires_at)

        embed = make_embed(
            None,
            "✅ Offer Posted",
            f"**ID:** `{offer_id}`\n**You have:** {have_card}\n**You want:** {want_card}\n**Expires in:** 48 hours",
            color=0x2ECC71,
        )
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="board", description="Browse open trade offers.")
    async def board(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return

        offers = await self.cog.bot.trade_service.get_open_offers(limit=10)
        if not offers:
            await smart_reply(interaction, embed=make_embed(None, "📋 Trade Board", "No open offers at the moment."), ephemeral=True)
            return

        lines = []
        for offer in offers:
            offer_id = offer.get("id", "???")
            poster_name = offer.get("poster_name", "Unknown")
            have_card = offer.get("have_card", "?")
            want_card = offer.get("want_card", "?")
            lines.append(f"`{offer_id}` • **{poster_name}** has {have_card} wants {want_card}")

        description = "\n".join(lines)
        embed = make_embed(None, "📋 Trade Board", description)
        embed.set_footer(text="Use /trade accept <id> to accept an offer")
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="accept", description="Accept a trade offer by ID.")
    @app_commands.describe(offer_id="The offer ID from /trade board")
    async def accept(self, interaction: discord.Interaction, offer_id: str) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return

        acceptor_id = str(interaction.user.id)
        offer = await self.cog.bot.trade_service.accept_offer(offer_id)
        if not offer:
            await smart_reply(
                interaction,
                embed=make_embed(None, "❌ Offer Not Found", "The offer is no longer available or has expired."),
                ephemeral=True,
            )
            return

        poster_id = offer.get("poster_id", "")
        have_card = offer.get("have_card", "")
        want_card = offer.get("want_card", "")

        data = await self.cog._load_trade_data()
        acceptor = get_player(data, acceptor_id)
        if not isinstance(acceptor, dict):
            await smart_reply(interaction, embed=make_embed(None, "❌ Error", "Your player data not found."), ephemeral=True)
            return

        acceptor_inventory = acceptor.get("user", {}).get("inventory", [])
        if not isinstance(acceptor_inventory, list):
            acceptor_inventory = []

        want_item = None
        for item in acceptor_inventory:
            if isinstance(item, dict) and str(item.get("name", "")).lower() == want_card.lower() and not item.get("trade_locked"):
                want_item = item
                break

        if not want_item:
            await smart_reply(
                interaction,
                embed=make_embed(None, "❌ Card Not Available", f"You don't have '{want_card}' to complete this trade."),
                ephemeral=True,
            )
            return

        def execute_trade(data: dict[str, Any]) -> tuple[bool, str]:
            poster = get_player(data, poster_id)
            acceptor = get_player(data, acceptor_id)

            if not isinstance(poster, dict) or not isinstance(acceptor, dict):
                return False, "Player data not found."

            poster_inv = poster.get("user", {}).get("inventory", [])
            acceptor_inv = acceptor.get("user", {}).get("inventory", [])

            if not isinstance(poster_inv, list) or not isinstance(acceptor_inv, list):
                return False, "Invalid inventory."

            have_idx = None
            for i, item in enumerate(poster_inv):
                if isinstance(item, dict) and str(item.get("name", "")).lower() == have_card.lower():
                    have_idx = i
                    break

            want_idx = None
            for i, item in enumerate(acceptor_inv):
                if isinstance(item, dict) and str(item.get("name", "")).lower() == want_card.lower():
                    want_idx = i
                    break

            if have_idx is None or want_idx is None:
                return False, "One of the cards no longer exists."

            have_item = poster_inv.pop(have_idx)
            want_item = acceptor_inv.pop(want_idx)

            have_item.pop("trade_locked", None)
            want_item.pop("trade_locked", None)

            acceptor_inv.append(have_item)
            poster_inv.append(want_item)

            return True, "ok"

        ok, msg = self.cog.bot.storage.with_lock(execute_trade)
        if not ok:
            await smart_reply(interaction, embed=make_embed(None, "❌ Trade Failed", msg), ephemeral=True)
            return

        embed = make_embed(
            None,
            "✅ Trade Complete",
            f"You received **{have_card}** and gave **{want_card}**.",
            color=0x2ECC71,
        )
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="cancel_offer", description="Cancel your open trade offer.")
    @app_commands.describe(offer_id="Your offer ID to cancel")
    async def cancel_offer(self, interaction: discord.Interaction, offer_id: str) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return

        user_id = str(interaction.user.id)
        offers = await self.cog.bot.trade_service.get_open_offers(limit=1000)
        item_uid = None
        for offer in offers:
            if offer.get("id") == offer_id and str(offer.get("poster_id", "")) == user_id:
                item_uid = offer.get("item_uid")
                break

        cancelled = await self.cog.bot.trade_service.cancel_offer(offer_id, user_id)

        if not cancelled:
            await smart_reply(
                interaction,
                embed=make_embed(None, "❌ Not Found", "Offer not found or you don't own it."),
                ephemeral=True,
            )
            return

        def unlock_card(data: dict[str, Any]) -> None:
            player = get_player(data, user_id)
            if isinstance(player, dict) and item_uid:
                inventory = player.get("user", {}).get("inventory", [])
                if isinstance(inventory, list):
                    _unlock(inventory, item_uid)

        self.cog.bot.storage.with_lock(unlock_card)
        await smart_reply(interaction, embed=make_embed(None, "✅ Cancelled", "Your trade offer has been cancelled."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradesCog(bot))
