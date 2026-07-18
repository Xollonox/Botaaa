"""Market UI views — BuyConfirmView and MarketPanel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord

from bot.data.constants import rarity_icon as _ri
from bot.utils.interaction_visibility import error_reply
from bot.utils.market_logic import (
    PAGE_SIZE,
    SORT_LABELS,
    apply_sort,
    build_market_embed,
    fee_percent_for_settings,
    get_active_listings,
    market_root,
)
from bot.utils.squad_logic import get_player
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed

if TYPE_CHECKING:
    from bot.features.market import MarketCog

logger = logging.getLogger(__name__)


async def _market_settings(cog: "MarketCog") -> dict[str, Any]:
    try:
        return await cog.bot.market_service.get_settings()
    except (TypeError, ValueError, AttributeError):
        logger.exception("Failed to load market settings")
        return {}


class BuyConfirmView(discord.ui.View):
    def __init__(self, cog: "MarketCog", buyer_id: str, listing_id: str, price: int, card_name: str) -> None:
        super().__init__(timeout=60)
        self.cog        = cog
        self.buyer_id   = buyer_id
        self.listing_id = listing_id
        self.price      = price
        self.card_name  = card_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.buyer_id:
            await error_reply(interaction, "Not your purchase.")
            return False
        return True

    @discord.ui.button(label="🛒 Confirm Buy", style=discord.ButtonStyle.success, row=0)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        user_id = self.buyer_id
        # Pre-fetch async data before entering the sync with_lock closure
        prefetched_listing = await self.cog.bot.market_service.get_listing(self.listing_id)
        mkt_settings = await _market_settings(self.cog)
        claimed_player_listing = False
        if isinstance(prefetched_listing, dict):
            seller_id = str(prefetched_listing.get("seller_id", ""))
            if seller_id and seller_id != "owner":
                claimed_player_listing = await self.cog.bot.market_service.delete_listing(self.listing_id)
                if not claimed_player_listing:
                    await interaction.response.send_message("Listing no longer exists.", ephemeral=True)
                    return

        def mutate(data: dict[str, Any]) -> tuple[bool, str, bool]:
            m        = market_root(data)
            listings = m.get("listings", {})

            is_featured = False
            is_special  = False
            listing: dict[str, Any] | None = None

            featured = m.get("featured")
            if isinstance(featured, dict) and str(featured.get("id", "")) == self.listing_id:
                if int(featured.get("expires_at", 0)) <= now_ts():
                    return False, "expired", False
                listing = featured
                is_featured = True

            special = m.get("special_offer")
            if not listing and isinstance(special, dict) and str(special.get("id", "")) == self.listing_id:
                if int(special.get("expires_at", 0)) <= now_ts():
                    return False, "expired", False
                listing = special
                is_special = True

            if not listing:
                listing = prefetched_listing
                if not isinstance(listing, dict):
                    listing = listings.get(self.listing_id) if isinstance(listings, dict) else None
            if not isinstance(listing, dict):
                return False, "not_found", False
            if listing.get("sold"):
                return False, "already_sold", False
            if str(listing.get("seller_id", "")) == user_id:
                return False, "own_listing", False

            price = int(listing.get("price", 0))

            buyer = get_player(data, user_id)
            if not isinstance(buyer, dict):
                return False, "buyer_not_found", False
            buyer_user = buyer.get("user", {})
            buyer_inv = buyer_user.setdefault("inventory", [])
            if not isinstance(buyer_inv, list):
                buyer_inv = []
                buyer_user["inventory"] = buyer_inv

            bal = int(buyer_user.get("balance", 0))
            if bal < price:
                return False, f"insufficient:{bal}:{price}", False

            card_def_name = str(listing.get("card_name", ""))

            seller_id = str(listing.get("seller_id", ""))
            if not is_featured and not is_special and seller_id and seller_id != "owner":
                seller = get_player(data, seller_id)
                seller_uid = str(listing.get("card_uid", ""))
                if not isinstance(seller, dict) or not seller_uid:
                    return False, "seller_card_missing", False

                seller_user = seller.get("user", {})
                s_inv = seller_user.get("inventory", []) if isinstance(seller_user, dict) else []
                if not isinstance(s_inv, list):
                    return False, "seller_card_missing", False

                moved_card: dict[str, Any] | None = None
                for idx, item in enumerate(s_inv):
                    if isinstance(item, dict) and str(item.get("uid", "")) == seller_uid:
                        moved_card = s_inv.pop(idx)
                        break
                if moved_card is None:
                    return False, "seller_card_missing", False

                moved_card["market_locked"] = False
                buyer_user["balance"] = bal - price
                fee_percent = fee_percent_for_settings(mkt_settings)
                payout = max(0, price - int(round(price * (fee_percent / 100.0))))
                seller_user["balance"] = int(seller_user.get("balance", 0)) + payout
                buyer_inv.append(moved_card)

                if isinstance(listings, dict):
                    listings.pop(self.listing_id, None)
                return True, "ok", True

            cards = data.get("cards", {})
            card_def = cards.get(card_def_name, {}) if isinstance(cards, dict) else {}
            from bot.utils.cards_logic import build_card_instance
            instance = build_card_instance(card_def if isinstance(card_def, dict) else {}, acquired_at=now_ts())
            instance["card_name"] = card_def_name
            instance["rarity"] = str(listing.get("rarity", "Common"))
            buyer_user["balance"] = bal - price
            buyer_inv.append(instance)

            if is_featured:
                stock = int(listing.get("stock", -1))
                if stock == -1:
                    pass
                elif stock <= 1:
                    m["featured"] = None
                else:
                    m["featured"]["stock"] = stock - 1
            elif is_special:
                stock = int(listing.get("stock", -1))
                if stock == -1:
                    pass
                elif stock <= 1:
                    m["special_offer"] = None
                else:
                    m["special_offer"]["stock"] = stock - 1

            return True, "ok", False

        try:
            ok, reason, delete_player_listing = self.cog.bot.storage.with_lock(mutate)
        except Exception:
            if claimed_player_listing and isinstance(prefetched_listing, dict):
                await self.cog.bot.market_service.upsert_listing(self.listing_id, prefetched_listing)
            raise

        if not ok:
            if claimed_player_listing and isinstance(prefetched_listing, dict):
                await self.cog.bot.market_service.upsert_listing(self.listing_id, prefetched_listing)
            msgs = {
                "not_found":           "Listing no longer exists.",
                "already_sold":        "This card was already sold.",
                "own_listing":         "You can't buy your own listing.",
                "expired":             "This listing has expired.",
                "buyer_not_found":     "Player profile not found.",
                "seller_card_missing": "Seller card is no longer available.",
            }
            msg = msgs.get(reason, reason)
            if reason.startswith("insufficient:"):
                _, have, need = reason.split(":")
                msg = f"Not enough coins. You have {int(have):,} but need {int(need):,}."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if delete_player_listing and not claimed_player_listing:
            # Legacy JSON-only listing: remove any late SQLite mirror too.
            await self.cog.bot.market_service.delete_listing(self.listing_id)

        body = (
            f"**🛒 Purchase Complete!**\n"
            f"{self.card_name}\n"
            f"💰 -{self.price:,} coins\n"
            "Card added to your inventory\n"
        )
        embed = make_embed(None, "LOOKISM HXCC • MARKET", body, color=0x2ECC71)
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message("Purchase cancelled.", ephemeral=True)
        self.stop()


class MarketPanel(discord.ui.View):
    def __init__(self, cog: "MarketCog", invoker_id: int, initial_data: dict[str, Any] | None = None) -> None:
        super().__init__(timeout=180)
        self.cog         = cog
        self.invoker_id  = invoker_id
        self.page        = 0
        self.sort_key    = "latest"
        self.selected_id: str | None = None
        self.message: discord.Message | None = None
        self._rebuild(initial_data)

    def _rebuild(self, data: dict[str, Any] | None = None) -> None:
        for child in list(self.children):
            if isinstance(child, (discord.ui.Select, discord.ui.Button)):
                self.remove_item(child)

        sort_select = discord.ui.Select(
            placeholder="🔽 Sort by...",
            options=[discord.SelectOption(label=label, value=key, default=key == self.sort_key)
                     for key, label in SORT_LABELS.items()],
            row=0,
        )
        sort_select.callback = self._on_sort
        self.add_item(sort_select)

        if data is None:
            data = {}
        all_listings = apply_sort(get_active_listings(data), self.sort_key)
        page_items   = all_listings[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        m            = market_root(data)
        featured     = m.get("featured")
        special      = m.get("special_offer")

        listing_opts = []
        if isinstance(featured, dict) and int(featured.get("expires_at", 0)) > now_ts():
            listing_opts.append(discord.SelectOption(
                label=f"⭐ {str(featured.get('card_name','?'))[:40]}",
                value=str(featured.get("id", "featured")),
                description=f"{int(featured.get('price',0)):,} coins • Featured",
                default=self.selected_id == str(featured.get("id", "")),
            ))
        if isinstance(special, dict) and int(special.get("expires_at", 0)) > now_ts():
            listing_opts.append(discord.SelectOption(
                label=f"🎁 {str(special.get('card_name','?'))[:40]}",
                value=str(special.get("id", "special")),
                description=f"{int(special.get('price',0)):,} coins • Special Offer",
                default=self.selected_id == str(special.get("id", "")),
            ))
        for listing in page_items[:23]:
            lid    = str(listing.get("id", ""))
            name   = str(listing.get("card_name", "?"))
            rarity = str(listing.get("rarity", ""))
            price  = int(listing.get("price", 0))
            listing_opts.append(discord.SelectOption(
                label=f"{_ri(rarity)} {name[:50]}",
                value=lid,
                description=f"{price:,} coins • @{str(listing.get('seller_name','?'))[:20]}",
                default=self.selected_id == lid,
            ))
        if listing_opts:
            listing_select = discord.ui.Select(
                placeholder="🃏 Select a listing...",
                options=listing_opts[:25],
                row=1,
            )
            listing_select.callback = self._on_select
            self.add_item(listing_select)

        prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=2)
        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary, row=2)
        total_pages = max(1, (len(all_listings) + PAGE_SIZE - 1) // PAGE_SIZE)
        prev_btn.disabled = self.page <= 0
        next_btn.disabled = self.page >= total_pages - 1
        prev_btn.callback = self._on_prev
        next_btn.callback = self._on_next
        self.add_item(prev_btn)
        self.add_item(next_btn)

        if self.selected_id:
            buy_btn = discord.ui.Button(label="🛒 Buy Selected", style=discord.ButtonStyle.success, row=2)
            buy_btn.callback = self._on_buy
            self.add_item(buy_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This market panel belongs to another player.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.exception("Failed to disable market panel after timeout")

    async def _refresh(self, interaction: discord.Interaction) -> None:
        data = await self.cog._load_market_data()
        self._rebuild(data)
        embed, _ = build_market_embed(data, self.page, self.sort_key, self.selected_id)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_sort(self, interaction: discord.Interaction) -> None:
        self.sort_key    = interaction.data["values"][0]
        self.page        = 0
        self.selected_id = None
        await self._refresh(interaction)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        self.selected_id = interaction.data["values"][0]
        await self._refresh(interaction)

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self.selected_id = None
        await self._refresh(interaction)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        data = await self.cog._load_market_data()
        total = max(1, (len(get_active_listings(data)) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = min(total - 1, self.page + 1)
        self.selected_id = None
        await self._refresh(interaction)

    async def _on_buy(self, interaction: discord.Interaction) -> None:
        if not self.selected_id:
            await interaction.response.send_message("Select a listing first.", ephemeral=True)
            return
        data = await self.cog._load_market_data()
        m    = market_root(data)

        listing: dict[str, Any] | None = None
        for src in [m.get("featured"), m.get("special_offer")]:
            if isinstance(src, dict) and str(src.get("id", "")) == self.selected_id:
                listing = src
                break
        if not listing:
            listing = await self.cog.bot.market_service.get_listing(self.selected_id)
            if not isinstance(listing, dict):
                listings = m.get("listings", {})
                if isinstance(listings, dict):
                    listing = listings.get(self.selected_id)

        if not isinstance(listing, dict):
            await error_reply(interaction, "Listing not found.")
            return

        price     = int(listing.get("price", 0))
        card_name = str(listing.get("card_name", "?"))
        rarity    = str(listing.get("rarity", ""))

        body = (
            f"**🛒 Confirm Purchase**\n"
            f"{_ri(rarity)} {card_name}  [{rarity}]\n"
            f"💰 {price:,} coins\n"
            "Are you sure?\n"
        )
        embed = make_embed(None, "LOOKISM HXCC • MARKET", body, color=0xE11D48)
        view = BuyConfirmView(self.cog, str(interaction.user.id), self.selected_id, price, card_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
