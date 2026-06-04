"""Owner-only market management commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from bot.config import OWNER_GUILD_ID

from bot.utils.checks import is_owner
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class MarketOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _deny(self, data: dict, interaction: discord.Interaction) -> None:
        raise RuntimeError

    def _card_choices(self, data: dict[str, object], current: str) -> list[app_commands.Choice[str]]:
        cards = data.get("cards", {}) if isinstance(data, dict) else {}
        cur = current.lower().strip()
        out = []
        if isinstance(cards, dict):
            for name in cards.keys():
                n = str(name)
                if cur and cur not in n.lower():
                    continue
                out.append(app_commands.Choice(name=n[:100], value=n))
                if len(out) >= 25:
                    break
        return out

    @app_commands.command(name="o_market_toggle", description="Owner: toggle market.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_toggle(self, interaction: discord.Interaction, enabled: bool) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        self.bot.market_service.set_enabled(bool(enabled))
        data = self.bot.storage.load()
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Market Updated", f"Enabled: {enabled}"), ephemeral=True)

    @app_commands.command(name="o_market_set_fee", description="Owner: set market fee percent.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_set_fee(self, interaction: discord.Interaction, fee_percent: app_commands.Range[int, 0, 25]) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        self.bot.market_service.set_fee_percent(int(fee_percent))
        data = self.bot.storage.load()
        await smart_reply(interaction, embed=make_embed(data, f"{e('fee', data)} Fee Updated", f"Fee: {fee_percent}%"), ephemeral=True)

    @app_commands.command(name="o_market_set_max_listings", description="Owner: set max listings per user.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_set_max_listings(self, interaction: discord.Interaction, max: app_commands.Range[int, 1, 50]) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        self.bot.market_service.set_max_listings(int(max))
        data = self.bot.storage.load()
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Max Listings Updated", f"Max: {max}"), ephemeral=True)

    @app_commands.command(name="o_market_store_add", description="Owner: add/update official store item.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_store_add(
        self,
        interaction: discord.Interaction,
        card_name: str,
        stock: app_commands.Range[int, -1, 999_999],
        price_override: app_commands.Range[int, 0, None] | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        ok, reason = self.bot.market_service.upsert_store_item(
            card_name=card_name,
            stock=int(stock),
            price_override=int(price_override) if price_override is not None else None,
        )
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Store Update Failed", reason), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('store', data)} Store Item Updated", f"{card_name} added/updated."), ephemeral=True)

    @o_market_store_add.autocomplete("card_name")
    async def o_market_store_add_card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        return self._card_choices(data, current)

    @app_commands.command(name="o_market_store_remove", description="Owner: remove official store item.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_store_remove(self, interaction: discord.Interaction, card_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        self.bot.market_service.remove_store_item(card_name)
        data = self.bot.storage.load()
        await smart_reply(interaction, embed=make_embed(data, f"{e('delete', data)} Store Item Removed", card_name), ephemeral=True)

    @o_market_store_remove.autocomplete("card_name")
    async def o_market_store_remove_card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        items = data.get("market", {}).get("store", {}).get("items", {}) if isinstance(data.get("market", {}), dict) else {}
        cur = current.lower()
        return [app_commands.Choice(name=str(k)[:100], value=str(k)) for k in items.keys() if not cur or cur in str(k).lower()][:25] if isinstance(items, dict) else []

    @app_commands.command(name="o_market_store_toggle", description="Owner: enable/disable store item.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_store_toggle(self, interaction: discord.Interaction, card_name: str, enabled: bool) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        ok, reason = self.bot.market_service.toggle_store_item(card_name, bool(enabled))
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Store Toggle Failed", reason), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Store Item Toggled", f"{card_name}: {enabled}"), ephemeral=True)

    @o_market_store_toggle.autocomplete("card_name")
    async def o_market_store_toggle_card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self.o_market_store_remove_card_autocomplete(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketOwnerCog(bot))
