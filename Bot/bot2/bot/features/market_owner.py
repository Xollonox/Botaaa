"""Owner-only market management commands."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.utils.checks import is_owner
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply



class MarketOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="o_market_toggle")
    async def o_market_toggle(self, ctx: commands.Context, enabled: bool) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        await self.bot.market_service.set_enabled(bool(enabled))
        data = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('ok', data)} Market Updated", f"Enabled: {enabled}"), ephemeral=True)

    @commands.command(name="o_market_set_fee")
    async def o_market_set_fee(self, ctx: commands.Context, fee_percent: int) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        await self.bot.market_service.set_fee_percent(int(fee_percent))
        data = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('fee', data)} Fee Updated", f"Fee: {fee_percent}%"), ephemeral=True)

    @commands.command(name="o_market_set_max_listings")
    async def o_market_set_max_listings(self, ctx: commands.Context, max: int) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        await self.bot.market_service.set_max_listings(int(max))
        data = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('ok', data)} Max Listings Updated", f"Max: {max}"), ephemeral=True)

    @commands.command(name="o_market_store_add")
    async def o_market_store_add(
        self,
        ctx: commands.Context,
        card_name: str,
        stock: int,
        price_override: int | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        ok, reason = await self.bot.market_service.upsert_store_item(
            card_name=card_name,
            stock=int(stock),
            price_override=int(price_override) if price_override is not None else None,
        )
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(ctx, embed=make_embed(data, f"{e('warning', data)} Store Update Failed", reason), ephemeral=True)
            return
        await smart_reply(ctx, embed=make_embed(data, f"{e('store', data)} Store Item Updated", f"{card_name} added/updated."), ephemeral=True)

    @commands.command(name="o_market_store_remove")
    async def o_market_store_remove(self, ctx: commands.Context, card_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        await self.bot.market_service.remove_store_item(card_name)
        data = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('delete', data)} Store Item Removed", card_name), ephemeral=True)

    @commands.command(name="o_market_store_toggle")
    async def o_market_store_toggle(self, ctx: commands.Context, card_name: str, enabled: bool) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        ok, reason = await self.bot.market_service.toggle_store_item(card_name, bool(enabled))
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(ctx, embed=make_embed(data, f"{e('warning', data)} Store Toggle Failed", reason), ephemeral=True)
            return
        await smart_reply(ctx, embed=make_embed(data, f"{e('ok', data)} Store Item Toggled", f"{card_name}: {enabled}"), ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketOwnerCog(bot))
