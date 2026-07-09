"""Market — featured card, special offers, player listings, buy/sell."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import OWNER_GUILD_ID
from bot.data.constants import rarity_icon as _ri
from bot.features.market_views import BuyConfirmView, MarketPanel  # noqa: F401  (BuyConfirmView re-exported for callers)
from bot.utils.cards_logic import find_catalog_card
from bot.utils.checks import ensure_registered, is_owner
from bot.utils.interaction_visibility import smart_reply
from bot.utils.market_logic import (
    build_market_embed,
    create_listing_id,
    ensure_market_structure,
    fee_percent_for_settings,
    market_root,
    price_range_for_settings,
)
from bot.utils.squad_logic import get_player
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)
logger = logging.getLogger(__name__)


def _card_name_choices(data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete from card catalog for owner commands."""
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        return []
    token = str(current).lower()
    out: list[app_commands.Choice[str]] = []
    for name, card in cards.items():
        if not isinstance(card, dict):
            continue
        if token and token not in str(name).lower():
            continue
        rarity = str(card.get("rarity", ""))
        label  = f"{name}  [{rarity}]" if rarity else str(name)
        out.append(app_commands.Choice(name=label[:100], value=str(name)))
        if len(out) >= 25:
            break
    return out


async def _market_settings(cog: "MarketCog") -> dict[str, Any]:
    try:
        return await cog.bot.market_service.get_settings()
    except (TypeError, ValueError, AttributeError):
        logger.exception("Failed to load market settings")
        return {}


async def _price_range_for(cog: "MarketCog", rarity: str) -> tuple[int, int]:
    return price_range_for_settings(await _market_settings(cog), rarity)


async def _fee_percent_for(cog: "MarketCog") -> int:
    return fee_percent_for_settings(await _market_settings(cog))


class MarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _load_market_data(self) -> dict[str, Any]:
        data = self.bot.storage.load()
        return await self.bot.market_service.hydrate_json_market_listings(data)

    @app_commands.command(name="o_feature_card", description="Owner: set the featured card of the day.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_feature_card(
        self,
        interaction: discord.Interaction,
        card_name: str,
        price: app_commands.Range[int, 1, 999_999_999],
        arc: str = "—",
        stock: app_commands.Range[int, -1, 999_999] = -1,
        expires_hours: app_commands.Range[int, 1, 72] = 24,
    ) -> None:
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(None, "❌ Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> None:
            m = market_root(data)
            cards    = data.get("cards", {})
            card_def = find_catalog_card(cards, card_name) if isinstance(cards, dict) else None
            if not isinstance(card_def, dict):
                card_def = {}
            image_url = str(card_def.get("image_url", "")).strip() if isinstance(card_def, dict) else ""
            rarity    = str(card_def.get("rarity", "")).strip() if isinstance(card_def, dict) else ""
            card_arc  = str(arc).strip() or str(card_def.get("arc", "—")).strip() if isinstance(card_def, dict) else str(arc).strip()
            m["featured"] = {
                "id":          str(uuid.uuid4()),
                "card_name":   card_name,
                "rarity":      rarity,
                "price":       int(price),
                "arc":         card_arc,
                "stock":       int(stock),
                "seller_id":   "owner",
                "seller_name": "HXCC Staff",
                "image_url":   image_url,
                "expires_at":  now_ts() + expires_hours * 3600,
            }

        self.bot.storage.with_lock(mutate)
        stock_text = "∞ Unlimited" if stock == -1 else str(stock)
        body = (
            f"╭─ ⭐ Featured Card Set\n"
            f"│ {card_name}\n"
            f"│ 💰 {price:,} coins\n"
            f"│ 📦 Stock: {stock_text}\n"
            f"│ 🌍 Arc: {arc}\n"
            f"│ ⏳ {expires_hours}h\n"
            "╰────────────────"
        )
        embed = make_embed(None, "LOOKISM HXCC • MARKET", body, color=0xF39C12)
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @o_feature_card.autocomplete("card_name")
    async def o_feature_card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _card_name_choices(await self._load_market_data(), current)

    @app_commands.command(name="o_special_offer", description="Owner: post a special offer.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_special_offer(
        self,
        interaction: discord.Interaction,
        card_name: str,
        price: app_commands.Range[int, 1, 999_999_999],
        arc: str = "—",
        stock: app_commands.Range[int, -1, 999_999] = -1,
        expires_hours: app_commands.Range[int, 1, 72] = 12,
    ) -> None:
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(None, "❌ Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> None:
            m = market_root(data)
            cards    = data.get("cards", {})
            card_def = find_catalog_card(cards, card_name) if isinstance(cards, dict) else None
            if not isinstance(card_def, dict):
                card_def = {}
            image_url = str(card_def.get("image_url", "")).strip() if isinstance(card_def, dict) else ""
            rarity    = str(card_def.get("rarity", "")).strip() if isinstance(card_def, dict) else ""
            card_arc  = str(arc).strip() or str(card_def.get("arc", "—")).strip() if isinstance(card_def, dict) else str(arc).strip()
            m["special_offer"] = {
                "id":          str(uuid.uuid4()),
                "card_name":   card_name,
                "rarity":      rarity,
                "price":       int(price),
                "arc":         card_arc,
                "stock":       int(stock),
                "seller_id":   "owner",
                "seller_name": "HXCC Staff",
                "image_url":   image_url,
                "expires_at":  now_ts() + expires_hours * 3600,
            }

        self.bot.storage.with_lock(mutate)
        stock_text = "∞ Unlimited" if stock == -1 else str(stock)
        body = (
            f"╭─ 🎁 Special Offer Set\n"
            f"│ {card_name}\n"
            f"│ 💰 {price:,} coins\n"
            f"│ 📦 Stock: {stock_text}\n"
            f"│ 🌍 Arc: {arc}\n"
            f"│ ⏳ {expires_hours}h\n"
            "╰────────────────"
        )
        embed = make_embed(None, "LOOKISM HXCC • MARKET", body, color=0xE11D48)
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @o_special_offer.autocomplete("card_name")
    async def o_special_offer_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return _card_name_choices(await self._load_market_data(), current)

    @app_commands.command(name="o_market_remove", description="Owner: force remove any listing.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_remove(self, interaction: discord.Interaction, listing_id: str) -> None:
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(None, "❌ Owner Only", "Not allowed."), ephemeral=True)
            return

        active_listings = await self.bot.market_service.get_active_listings()

        def mutate(data: dict[str, Any]) -> tuple[bool, bool]:
            m = market_root(data)
            listings = m.setdefault("listings", {})
            listings.update(active_listings)
            if listing_id in listings:
                listing   = listings.pop(listing_id)
                seller_id = str(listing.get("seller_id", ""))
                card_uid  = str(listing.get("card_uid", ""))
                if seller_id and card_uid:
                    seller = get_player(data, seller_id)
                    if isinstance(seller, dict):
                        inv = seller.get("user", {}).get("inventory", [])
                        for item in inv:
                            if isinstance(item, dict) and str(item.get("uid", "")) == card_uid:
                                item["market_locked"] = False
                                break
                return True, True
            return False, False

        ok, should_delete_sqlite = self.bot.storage.with_lock(mutate)
        if ok and should_delete_sqlite:
            await self.bot.market_service.delete_listing(listing_id)
        msg = "✅ Listing removed." if ok else "❌ Listing not found."
        await smart_reply(interaction, embed=make_embed(None, "Market", msg), ephemeral=True)

    @app_commands.command(name="o_market_set_quick_sell", description="Owner: set quick-sell value by rarity.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_market_set_quick_sell(
        self,
        interaction: discord.Interaction,
        rarity: str,
        value: app_commands.Range[int, 0, 999_999_999],
    ) -> None:
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(None, "❌ Owner Only", "Not allowed."), ephemeral=True)
            return

        await self.bot.market_service.set_quick_sell_value(str(rarity), int(value))
        await smart_reply(interaction, embed=make_embed(None, "✅ Updated", f"{rarity} quick sell → {value:,} coins"), ephemeral=True)


    @commands.group(name="market", invoke_without_subcommand=True)
    async def market(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @market.command(name="browse")
    async def market_browse(self, ctx: commands.Context) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return
        data = await self._load_market_data()
        panel = MarketPanel(self, ctx.author.id, data)
        embed, _ = build_market_embed(data, 0, "latest", None)
        panel.message = await ctx.send(embed=embed, view=panel)

    @market.command(name="add")
    async def market_add(
        self,
        ctx: commands.Context,
        card_name: str,
        price: int,
        arc: str = "—",
    ) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return

        user_id = str(ctx.author.id)
        mkt_settings = await _market_settings(self)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str, dict[str, Any] | None]:
            player = get_player(data, user_id)
            if not isinstance(player, dict):
                return False, "not_registered", "", None
            user = player.get("user", {})
            inv  = user.get("inventory", []) if isinstance(user, dict) else []
            if not isinstance(inv, list):
                return False, "no_inventory", "", None

            card = next((item for item in inv
                         if isinstance(item, dict)
                         and str(item.get("card_name", "")).lower() == card_name.lower()
                         and not item.get("locked")
                         and not item.get("squad_locked")
                         and not item.get("market_locked")
                         and not item.get("trade_locked")), None)
            if not isinstance(card, dict):
                return False, "card_not_found", "", None

            rarity = str(card.get("rarity", "Common"))
            lo, hi = price_range_for_settings(mkt_settings, rarity)
            if not (lo <= price <= hi):
                return False, f"price_range:{rarity}:{lo}:{hi}", "", None

            card["market_locked"] = True
            lid = create_listing_id()
            cards    = data.get("cards", {})
            card_def = cards.get(str(card.get("card_name", "")), {}) if isinstance(cards, dict) else {}
            if not isinstance(card_def, dict):
                card_def = next((v for k, v in cards.items()
                                 if str(k).lower() == str(card.get("card_name","")).lower()), {}) if isinstance(cards, dict) else {}
            image_url = str(card_def.get("image_url", "")).strip() if isinstance(card_def, dict) else ""
            arc_val   = str(arc).strip() or "—"

            m = market_root(data)
            listing_payload = {
                "id":          lid,
                "card_name":   str(card.get("card_name", card_name)),
                "card_uid":    str(card.get("uid", "")),
                "rarity":      rarity,
                "price":       int(price),
                "seller_id":   user_id,
                "seller_name": str(user.get("name", user_id)),
                "arc":         arc_val,
                "image_url":   image_url,
                "listed_at":   now_ts(),
                "expires_at":  now_ts() + 604800,
                "sold":        False,
            }
            m["listings"][lid] = listing_payload
            return True, rarity, lid, listing_payload

        ok, result, listing_id, listing_payload = self.bot.storage.with_lock(mutate)
        if ok and listing_payload is not None:
            try:
                await self.bot.market_service.upsert_listing(listing_id, listing_payload)
            except Exception:
                logger.exception("Failed to persist market listing %s to SQLite; rolling back JSON state", listing_id)

                def rollback(data: dict[str, Any]) -> None:
                    m = market_root(data)
                    m.get("listings", {}).pop(listing_id, None)
                    player = get_player(data, user_id)
                    user = player.get("user", {}) if isinstance(player, dict) else {}
                    inv = user.get("inventory", []) if isinstance(user, dict) else []
                    if not isinstance(inv, list):
                        return
                    card_uid = str(listing_payload.get("card_uid", ""))
                    for item in inv:
                        if isinstance(item, dict) and str(item.get("uid", "")) == card_uid:
                            item["market_locked"] = False
                            break

                self.bot.storage.with_lock(rollback)
                await smart_reply(
                    ctx,
                    embed=make_embed(None, "❌ Listing Failed", "Market storage failed. Your card was not listed."),
                )
                return
        if not ok:
            msgs = {
                "not_registered": "You are not registered.",
                "card_not_found": f"**{card_name}** not found in your inventory (must be unlocked and not in squad/market).",
            }
            msg = msgs.get(result, result)
            if result.startswith("price_range:"):
                _, rarity, lo, hi = result.split(":")
                msg = f"Price must be between **{int(lo):,}** and **{int(hi):,}** coins for **{rarity}** cards."
            await smart_reply(ctx, embed=make_embed(None, "❌ Listing Failed", msg))
            return

        body = (
            f"╭─ ✅ Listed!\n"
            f"│ {card_name}  [{result}]\n"
            f"│ 💰 {price:,} coins\n"
            f"│ 🌍 Arc: {arc}\n"
            "│ Use !market browse to view\n"
            "╰────────────────"
        )
        embed = make_embed(None, "LOOKISM HXCC • MARKET", body, color=0x2ECC71)
        await smart_reply(ctx, embed=embed)

    @market.command(name="remove")
    async def market_remove(self, ctx: commands.Context, card_name: str) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return
        user_id = str(ctx.author.id)

        active_listings = await self.bot.market_service.get_active_listings()

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str]:
            m        = market_root(data)
            listings = m.setdefault("listings", {})
            listings.update(active_listings)
            if not isinstance(listings, dict):
                return False, "no_listings", ""
            listing = next(
                ((lid, l) for lid, l in listings.items()
                 if isinstance(l, dict)
                 and str(l.get("seller_id", "")) == user_id
                 and str(l.get("card_name", "")).lower() == card_name.lower()
                 and not l.get("sold")),
                None,
            )
            if not listing:
                return False, "not_found", ""
            lid, l = listing
            listings.pop(lid, None)
            card_uid = str(l.get("card_uid", ""))
            player   = get_player(data, user_id)
            if isinstance(player, dict) and card_uid:
                inv = player.get("user", {}).get("inventory", [])
                for item in inv:
                    if isinstance(item, dict) and str(item.get("uid", "")) == card_uid:
                        item["market_locked"] = False
                        break
            return True, str(l.get("card_name", card_name)), str(lid)

        ok, result, removed_lid = self.bot.storage.with_lock(mutate)
        if ok and removed_lid:
            await self.bot.market_service.delete_listing(removed_lid)
        if not ok:
            await smart_reply(ctx, embed=make_embed(None, "❌ Not Found", f"No active listing found for **{card_name}**."))
            return
        await smart_reply(ctx, embed=make_embed(None, "✅ Removed", f"**{result}** removed from market."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCog(bot))
