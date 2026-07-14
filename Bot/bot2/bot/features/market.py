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
        self.market_group = MarketGroup(self)
        self.bot.tree.add_command(self.market_group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.market_group.name, type=self.market_group.type)

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
        claimed_payload = active_listings.get(listing_id)
        if not isinstance(claimed_payload, dict) or not await self.bot.market_service.delete_listing(listing_id):
            await smart_reply(interaction, embed=make_embed(None, "Market", "❌ Listing not found."), ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, bool]:
            m = market_root(data)
            listings = m.setdefault("listings", {})
            if not isinstance(listings, dict):
                return False, False
            listing = listings.get(listing_id)
            if not isinstance(listing, dict):
                # SQLite is authoritative during migration, but restore only
                # the listing we atomically claimed -- never a stale snapshot
                # of every listing.
                listing = claimed_payload
                listings[listing_id] = listing
            if listing_id in listings:
                listing = listings.pop(listing_id)
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

        try:
            ok, _should_delete_sqlite = self.bot.storage.with_lock(mutate)
        except Exception:
            await self.bot.market_service.upsert_listing(listing_id, claimed_payload)
            raise
        if not ok:
            await self.bot.market_service.upsert_listing(listing_id, claimed_payload)
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


class MarketGroup(app_commands.Group):
    def __init__(self, cog: "MarketCog") -> None:
        super().__init__(name="market", description="Market commands")
        self.cog = cog

    @app_commands.command(name="browse", description="Browse the market.")
    async def browse(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return
        data = await self.cog._load_market_data()
        panel = MarketPanel(self.cog, interaction.user.id, data)
        embed, _ = build_market_embed(data, 0, "latest", None)
        await interaction.response.send_message(embed=embed, view=panel)
        panel.message = await interaction.original_response()

    @app_commands.command(name="add", description="List a card from your inventory for sale.")
    async def add(
        self,
        interaction: discord.Interaction,
        card_name: str,
        price: app_commands.Range[int, 1, 999_999_999],
        arc: str = "—",
    ) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return

        user_id = str(interaction.user.id)
        # Pre-fetch settings so the sync with_lock closure doesn't call async code
        mkt_settings = await _market_settings(self.cog)

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

        ok, result, listing_id, listing_payload = self.cog.bot.storage.with_lock(mutate)
        if ok and listing_payload is not None:
            try:
                await self.cog.bot.market_service.upsert_listing(listing_id, listing_payload)
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

                self.cog.bot.storage.with_lock(rollback)
                await smart_reply(
                    interaction,
                    embed=make_embed(None, "❌ Listing Failed", "Market storage failed. Your card was not listed."),
                    ephemeral=True,
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
            await smart_reply(interaction, embed=make_embed(None, "❌ Listing Failed", msg), ephemeral=True)
            return

        body = (
            f"╭─ ✅ Listed!\n"
            f"│ {card_name}  [{result}]\n"
            f"│ 💰 {price:,} coins\n"
            f"│ 🌍 Arc: {arc}\n"
            "│ Use /market browse to view\n"
            "╰────────────────"
        )
        embed = make_embed(None, "LOOKISM HXCC • MARKET", body, color=0x2ECC71)
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @add.autocomplete("card_name")
    async def add_card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        user_id = str(interaction.user.id)
        data = await self.cog._load_market_data()
        mkt_settings = await _market_settings(self.cog)
        player  = get_player(data, user_id)
        if not isinstance(player, dict):
            return []
        inv = player.get("user", {}).get("inventory", [])
        if not isinstance(inv, list):
            return []
        token = current.lower()
        seen: set[str] = set()
        out: list[app_commands.Choice[str]] = []
        for item in inv:
            if not isinstance(item, dict):
                continue
            if item.get("locked") or item.get("squad_locked") or item.get("market_locked") or item.get("trade_locked"):
                continue
            name   = str(item.get("card_name", ""))
            rarity = str(item.get("rarity", ""))
            if not name or name in seen:
                continue
            if token and token not in name.lower():
                continue
            seen.add(name)
            lo, hi = price_range_for_settings(mkt_settings, rarity)
            out.append(app_commands.Choice(
                name=f"{_ri(rarity)} {name}  [{rarity}]  ({lo:,}–{hi:,})"[:100],
                value=name,
            ))
            if len(out) >= 25:
                break
        return out

    @app_commands.command(name="remove", description="Remove your market listing.")
    async def remove(self, interaction: discord.Interaction, card_name: str) -> None:
        if not await ensure_registered(interaction, self.cog.bot.storage):
            return
        user_id = str(interaction.user.id)

        # Pre-fetch active listings so the sync with_lock closure doesn't call async code
        active_listings = await self.cog.bot.market_service.get_active_listings()
        claimed = next(
            (
                (lid, row)
                for lid, row in active_listings.items()
                if isinstance(row, dict)
                and str(row.get("seller_id", "")) == user_id
                and str(row.get("card_name", "")).lower() == card_name.lower()
                and not row.get("sold")
            ),
            None,
        )
        if claimed is None:
            await smart_reply(interaction, embed=make_embed(None, "❌ Not Found", f"No active listing found for **{card_name}**."), ephemeral=True)
            return
        claimed_lid, claimed_payload = claimed
        if not await self.cog.bot.market_service.delete_listing(str(claimed_lid)):
            await smart_reply(interaction, embed=make_embed(None, "❌ Not Found", f"No active listing found for **{card_name}**."), ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str]:
            m        = market_root(data)
            listings = m.setdefault("listings", {})
            if not isinstance(listings, dict):
                return False, "no_listings", ""
            l = listings.get(str(claimed_lid))
            if not isinstance(l, dict):
                l = claimed_payload
                listings[str(claimed_lid)] = l
            if (
                str(l.get("seller_id", "")) != user_id
                or str(l.get("card_name", "")).lower() != card_name.lower()
                or l.get("sold")
            ):
                return False, "not_found", ""
            lid = str(claimed_lid)
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

        try:
            ok, result, _removed_lid = self.cog.bot.storage.with_lock(mutate)
        except Exception:
            await self.cog.bot.market_service.upsert_listing(str(claimed_lid), claimed_payload)
            raise
        if not ok:
            await self.cog.bot.market_service.upsert_listing(str(claimed_lid), claimed_payload)
            await smart_reply(interaction, embed=make_embed(None, "❌ Not Found", f"No active listing found for **{card_name}**."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(None, "✅ Removed", f"**{result}** removed from market."), ephemeral=True)

    @remove.autocomplete("card_name")
    async def remove_card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        user_id = str(interaction.user.id)
        data = await self.cog._load_market_data()
        m        = market_root(data)
        listings = m.get("listings", {})
        if not isinstance(listings, dict):
            return []
        token = current.lower()
        out: list[app_commands.Choice[str]] = []
        for lid, l in listings.items():
            if not isinstance(l, dict):
                continue
            if str(l.get("seller_id", "")) != user_id:
                continue
            if l.get("sold"):
                continue
            name   = str(l.get("card_name", ""))
            rarity = str(l.get("rarity", ""))
            price  = int(l.get("price", 0))
            if token and token not in name.lower():
                continue
            label = f"{_ri(rarity)} {name}  [{rarity}]  •  {price:,} coins"
            out.append(app_commands.Choice(name=label[:100], value=name))
            if len(out) >= 25:
                break
        return out


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCog(bot))
