"""Shop listing for packs and immediate buy+open flow."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import OWNER_GUILD_ID
from bot.utils.checks import is_owner
from bot.utils.pack_logic import ensure_packs_structure, format_rates_table, get_pack_by_name
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.features.packs import _add_packs_to_inventory, _open_pack_from_inventory, _packs_root, _wallet_balance, _set_wallet_balance
from bot.features.packs_panel import (
    _AnimView,
    PostRevealView,
    _anim_embed,
    _card_reveal_embed,
    animate_pack_open,
)

logger = logging.getLogger(__name__)

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


PRICE_FILTERS = {
    "all":     (0,      999_999_999),
    "cheap":   (0,      5_000),
    "mid":     (5_001,  20_000),
    "premium": (20_001, 999_999_999),
}

RARITY_OPTIONS = ["Common", "Rare", "Epic", "Legendary", "Mythical", "Infernal", "Abyssal"]

from bot.data.constants import RARITY_ICONS as _CANON_RARITY_ICONS
RARITY_ICONS = {k.lower(): v for k, v in _CANON_RARITY_ICONS.items()}

SORT_OPTIONS = {
    "price_asc":  ("💰 Price: Low → High",  lambda p: int(p.get("price", 0))),
    "price_desc": ("💰 Price: High → Low",  lambda p: -int(p.get("price", 0))),
    "name_asc":   ("🔤 Name: A → Z",        lambda p: str(p.get("name", "")).lower()),
}


def is_public_shop_pack(pack_key: str, pack: dict[str, Any]) -> bool:
    if str(pack_key) == "war_pack":
        return False
    return bool(pack.get("enabled", True)) and bool(pack.get("shop_visible", True))


def purchase_shop_pack(data: dict[str, Any], user_id: str, pack_key: str, qty: int, price: int) -> tuple[bool, str]:
    player = data.get("players", {}).get(str(user_id))
    if not isinstance(player, dict):
        return False, "not_registered"
    user = player.get("user", {})
    if not isinstance(user, dict):
        return False, "no_user"
    total_cost = int(price) * max(1, int(qty))
    bal = _wallet_balance(user)
    if bal < total_cost:
        return False, f"insufficient:{bal}:{total_cost}"
    _set_wallet_balance(user, bal - total_cost)
    _add_packs_to_inventory(data, str(user_id), str(pack_key), max(1, int(qty)))
    stats = data.setdefault("packs", {}).setdefault("stats", {})
    if isinstance(stats, dict):
        stats["total_spent"] = int(stats.get("total_spent", 0)) + int(total_cost)
    player_packs = player.setdefault("packs", {})
    if isinstance(player_packs, dict):
        player_packs["spent"] = int(player_packs.get("spent", 0)) + int(total_cost)
    return True, "ok"


def _apply_filters(
    packs: list[dict[str, Any]],
    price_filter: str,
    rarity_filter: str,
    sort_key: str,
) -> list[dict[str, Any]]:
    lo, hi = PRICE_FILTERS.get(price_filter, (0, 999_999_999))
    result = []
    for p in packs:
        price = int(p.get("price", 0))
        if not (lo <= price <= hi):
            continue
        if rarity_filter and rarity_filter != "all":
            rates = p.get("rates", {}) if isinstance(p.get("rates"), dict) else {}
            if not any(k.lower() == rarity_filter.lower() for k in rates):
                continue
        result.append(p)
    _, sort_fn = SORT_OPTIONS.get(sort_key, SORT_OPTIONS["price_asc"])
    result.sort(key=sort_fn)
    return result


class ShopFilterSelect(discord.ui.Select):
    def __init__(self, view: "ShopPages") -> None:
        options = [
            discord.SelectOption(label="📦 All Packs",        value="all",     default=view.price_filter == "all"),
            discord.SelectOption(label="💰 Cheap  (0–5k)",    value="cheap",   default=view.price_filter == "cheap"),
            discord.SelectOption(label="💰 Mid  (5k–20k)",    value="mid",     default=view.price_filter == "mid"),
            discord.SelectOption(label="💰 Premium  (20k+)",  value="premium", default=view.price_filter == "premium"),
        ]
        super().__init__(placeholder="🔽 Filter packs…", min_values=1, max_values=1, options=options, row=0)
        # Store state directly — never rely on self.view which discord.py can null
        self._cog = view.cog
        self._user_id = view.user_id
        self._shop_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v: ShopPages | None = self._shop_view
        if v is None or self._cog is None:
            await error_reply(interaction, "Panel expired. Run /shop again.")
            return
        if str(interaction.user.id) != self._user_id:
            await error_reply(interaction, "Not your panel.")
            return
        val = self.values[0]
        if val.startswith("rarity_"):
            v.rarity_filter = val[len("rarity_"):]
            v.price_filter = "all"
        else:
            v.price_filter = val
            v.rarity_filter = "all"
        v.page = 0
        await v._refresh_component(interaction)


class ShopSortSelect(discord.ui.Select):
    def __init__(self, view: "ShopPages") -> None:
        options = [
            discord.SelectOption(label=label, value=key, default=view.sort_key == key)
            for key, (label, _) in SORT_OPTIONS.items()
        ]
        super().__init__(placeholder="🔽 Sort packs…", min_values=1, max_values=1, options=options, row=1)
        self._cog = view.cog
        self._user_id = view.user_id
        self._shop_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v: ShopPages | None = self._shop_view
        if v is None or self._cog is None:
            await error_reply(interaction, "Panel expired. Run /shop again.")
            return
        if str(interaction.user.id) != self._user_id:
            await error_reply(interaction, "Not your panel.")
            return
        v.sort_key = self.values[0]
        v.page = 0
        await v._refresh_component(interaction)


class ShopBuyOpenButtons:
    """Holds the Buy 1 / Buy 10 button callbacks; attached to ShopPages row 4."""

    @staticmethod
    async def _buy_open(interaction: discord.Interaction, view: "ShopPages", qty: int) -> None:
        if str(interaction.user.id) != view.user_id:
            await error_reply(interaction, "Not your panel.")
            return
        if not view.selected_pack:
            await interaction.response.send_message("Select a pack first.", ephemeral=True)
            return
        filtered = view._filtered()
        pack = next((p for p in filtered if str(p.get("key", "")) == view.selected_pack), None)
        if not pack:
            await error_reply(interaction, "Pack not found.")
            return

        pack_key = str(pack.get("key", ""))
        pack_name = str(pack.get("name", "Pack"))
        price = int(pack.get("price", 0))
        total_cost = price * qty
        user_id = view.user_id

        # 1. Show initial animation frame
        class _AnimPanelProxy:
            """Minimal stand-in for PacksPanel so _AnimView works from shop."""
            def __init__(self2):
                self2.invoker_id = int(user_id)
                self2.skipped = False
                self2.message = None
        anim_view = _AnimView(_AnimPanelProxy())

        title = f"Buying {qty}x {pack_name}..."
        try:
            await interaction.response.edit_message(
                embed=_anim_embed(title, "⬛  ⬛  ⬛  ⬛  ⬛", "The pack is sealed..."),
                view=anim_view,
            )
        except Exception:
            logger.exception("[SHOP_BUY_OPEN] failed to show initial frame")
            return

        msg = interaction.message

        # 2. Mutate: deduct coins + open packs + add cards to inventory
        def mutate(data: dict[str, Any]) -> tuple[bool, str, list[dict[str, str]]]:
            ok, reason = purchase_shop_pack(data, user_id, pack_key, qty, price)
            if not ok:
                return False, reason, []
            rolls: list[dict[str, str]] = []
            for _ in range(qty):
                ok2, _, r = _open_pack_from_inventory(data, user_id, pack_key)
                if ok2:
                    rolls.extend(r)
            return True, "ok", rolls

        ok, reason, all_rolls = view.cog.bot.storage.with_lock(mutate)

        if not ok:
            msg_text = "Not registered." if reason == "not_registered" else reason
            if reason.startswith("insufficient:"):
                _, have, need = reason.split(":")
                msg_text = f"Not enough coins. You have **{int(have):,}** but need **{int(need):,}**."
            try:
                await msg.edit(
                    embed=make_embed(None, "❌ Purchase Failed", msg_text, color=0xE74C3C),
                    view=None,
                )
            except Exception:
                pass
            return

        if not all_rolls:
            try:
                await msg.edit(
                    embed=make_embed(None, "❌ Open Failed", "Could not open packs.", color=0xE74C3C),
                    view=None,
                )
            except Exception:
                pass
            return

        # 3. Run animation
        if msg and not anim_view.skipped:
            await animate_pack_open(msg, title, all_rolls, view.cog.bot.storage.load(), anim_view)

        await asyncio.sleep(0.3)

        # 4. Show post-reveal view (create a minimal stand-in for PacksPanel)
        dummy_panel = lambda: None  # noqa: E731
        dummy_panel.message = msg
        dummy_panel.current_slot = 0
        dummy_panel.invoker_id = int(user_id)
        dummy_panel._shop_view = view  # signals back_btn to return to shop

        reveal_view = PostRevealView(view.cog, int(user_id), all_rolls, pack_name, dummy_panel)
        reveal_view.message = msg
        first_embed = _card_reveal_embed(all_rolls[0], 1, len(all_rolls), pack_name)
        try:
            await msg.edit(embed=first_embed, view=reveal_view)
        except Exception:
            logger.exception("[SHOP_BUY_OPEN] failed to switch to reveal view")


class ShopPackSelect(discord.ui.Select):
    """Pack selector — shown on Row 3, triggers buy modal."""
    def __init__(self, view: "ShopPages", packs: list[dict[str, Any]]) -> None:
        opts = [
            discord.SelectOption(
                label=f"🎴 {str(p.get('name','Pack'))[:50]}",
                value=str(p.get("key", "")),
                description=f"💰 {int(p.get('price',0)):,} coins",
                default=view.selected_pack == str(p.get("key", "")),
            )
            for p in packs[:25]
        ]
        if not opts:
            opts = [discord.SelectOption(label="No packs available", value="none")]
        super().__init__(
            placeholder="🎴 Select a pack to buy...",
            options=opts,
            row=3,
        )
        self._cog        = view.cog
        self._user_id    = view.user_id
        self._shop_view  = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v = self._shop_view
        if v is None or self._cog is None:
            await error_reply(interaction, "Panel expired. Run /shop again.")
            return
        if str(interaction.user.id) != self._user_id:
            await error_reply(interaction, "Not your panel.")
            return
        val = self.values[0]
        if val == "none":
            await interaction.response.defer()
            return
        v.selected_pack = val
        await v._refresh_component(interaction)


class ShopPages(discord.ui.View):
    def __init__(self, cog: "ShopCog", user_id: str, packs: list[dict[str, Any]], title: str) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.all_packs = packs
        self.title = title
        self.page = 0
        self.page_size = 4
        self.price_filter  = "all"
        self.rarity_filter = "all"
        self.sort_key      = "price_asc"
        self.selected_pack: str | None = None
        self._rebuild_selects()

    def _filtered(self) -> list[dict[str, Any]]:
        return _apply_filters(self.all_packs, self.price_filter, self.rarity_filter, self.sort_key)

    def _max_page(self, filtered: list | None = None) -> int:
        f = filtered if filtered is not None else self._filtered()
        return max(0, (len(f) - 1) // self.page_size)

    def _rebuild_selects(self) -> None:
        # Remove old selects/nav, keep only buttons added by decorators
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
            elif isinstance(child, discord.ui.Button):
                self.remove_item(child)
        self.add_item(ShopFilterSelect(self))
        self.add_item(ShopSortSelect(self))
        # Re-add nav buttons manually at row 2
        prev = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=2)
        next_ = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary, row=2)
        filtered = self._filtered()
        prev.disabled = self.page <= 0
        next_.disabled = self.page >= self._max_page(filtered)
        prev.callback = self._on_prev
        next_.callback = self._on_next
        self.add_item(prev)
        self.add_item(next_)

        # Row 3 — Pack selector
        filtered = self._filtered()
        if filtered:
            self.add_item(ShopPackSelect(self, filtered))

        # Row 4 — Buy & Open buttons (only if pack selected)
        if self.selected_pack:
            pack = next((p for p in filtered if str(p.get("key","")) == self.selected_pack), None)
            if pack:
                buy1 = discord.ui.Button(
                    label=f"📦 Buy 1 & Open",
                    style=discord.ButtonStyle.success,
                    row=4,
                )
                buy1.callback = lambda i, v=self, q=1: ShopBuyOpenButtons._buy_open(i, v, q)  # type: ignore
                self.add_item(buy1)
                buy10 = discord.ui.Button(
                    label=f"📦 Buy 10 & Open",
                    style=discord.ButtonStyle.primary,
                    row=4,
                )
                buy10.callback = lambda i, v=self, q=10: ShopBuyOpenButtons._buy_open(i, v, q)  # type: ignore
                self.add_item(buy10)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    async def _refresh_component(self, interaction: discord.Interaction) -> bool:
        """Acknowledge a component promptly, then rebuild and edit its message."""
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            self._rebuild_selects()
            data = self.cog.bot.storage.load()
            await interaction.edit_original_response(embed=self.embed(data), view=self)
            return True
        except discord.NotFound:
            logger.warning(
                "Shop component interaction expired before refresh | user=%s message=%s",
                getattr(interaction.user, "id", "unknown"),
                getattr(getattr(interaction, "message", None), "id", "unknown"),
            )
            self.stop()
            return False

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            await error_reply(interaction, "Not your panel.")
            return
        self.page = max(0, self.page - 1)
        await self._refresh_component(interaction)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            await error_reply(interaction, "Not your panel.")
            return
        filtered = self._filtered()
        self.page = min(self._max_page(filtered), self.page + 1)
        await self._refresh_component(interaction)

    def _balance(self, data: dict[str, Any]) -> tuple[int, int]:
        """Return (coins, premium) for the current user."""
        player = data.get("players", {}).get(self.user_id, {})
        user = player.get("user", {}) if isinstance(player, dict) else {}
        coins = int(user.get("balance", user.get("coins", 0))) if isinstance(user, dict) else 0
        gems  = int(user.get("premium_balance", user.get("premium_currency", 0))) if isinstance(user, dict) else 0
        return coins, gems

    def embed(self, data: dict[str, Any]) -> discord.Embed:
        filtered = self._filtered()
        total_pages = self._max_page(filtered) + 1
        coins, gems = self._balance(data)

        # Active filter label
        if self.rarity_filter and self.rarity_filter != "all":
            filter_label = f"{RARITY_ICONS.get(self.rarity_filter, '•')} {self.rarity_filter.title()} packs"
        elif self.price_filter != "all":
            filter_label = {"cheap": "💰 Cheap (0–5k)", "mid": "💰 Mid (5k–20k)", "premium": "💰 Premium (20k+)"}.get(self.price_filter, "All")
        else:
            filter_label = "📦 All Packs"

        sort_label, _ = SORT_OPTIONS.get(self.sort_key, SORT_OPTIONS["price_asc"])

        wallet_block = box("Wallet", [
            f"💰 Coins: {coins:,}",
            f"💎 Gems:  {gems:,}",
        ])

        if not filtered:
            header = box("Filters", [f"Showing: {filter_label}", f"Sort: {sort_label}", "No packs match this filter."])
            return make_embed(data, f"{e('shop', data)} Shop", wallet_block + "\n\n" + header)

        start = self.page * self.page_size
        rows = filtered[start : start + self.page_size]
        blocks: list[str] = [
            wallet_block,
            box("Filters", [f"Showing: {filter_label}", f"Sort: {sort_label}", f"Page {self.page + 1}/{total_pages}"]),
        ]
        for pack in rows:
            price     = int(pack.get('price', 0))
            is_sel    = str(pack.get("key","")) == self.selected_pack
            marker    = "👉 " if is_sel else ""
            pack_lines = [f"💰 Price: {price:,} coins"]
            blocks.append(box(f"{e('pack', data)} {marker}{pack.get('name', 'Pack')}", pack_lines))

        return make_embed(data, f"{e('shop', data)} Shop", "\n\n".join(blocks))




class OwnerPackListPages(discord.ui.View):
    def __init__(self, cog: "ShopCog", user_id: str, lines: list[str]) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.lines = lines
        self.page = 0
        self.page_size = 8
        self._refresh()

    def _max_page(self) -> int:
        return max(0, (len(self.lines) - 1) // self.page_size)

    def _refresh(self) -> None:
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self._max_page()

    def embed(self, data: dict[str, Any]) -> discord.Embed:
        start = self.page * self.page_size
        chunk = self.lines[start : start + self.page_size]
        if not chunk:
            chunk = [f"{e('warning', data)} No packs configured."]
        return make_embed(data, f"{e('shop', data)} Pack List", "\n".join(chunk))

    async def _guard(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            await smart_reply(interaction, "Not your paginator.", ephemeral=True)
            return
        self.page = max(0, self.page - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.embed(self.cog.bot.storage.load()), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            await smart_reply(interaction, "Not your paginator.", ephemeral=True)
            return
        self.page = min(self._max_page(), self.page + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.embed(self.cog.bot.storage.load()), view=self)


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _pack_choices(self, data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
        ensure_packs_structure(data)
        definitions = data.get("packs", {}).get("definitions", {})
        out: list[app_commands.Choice[str]] = []
        token = str(current or "").lower()
        if not isinstance(definitions, dict):
            return out
        for key, pack in definitions.items():
            if not isinstance(pack, dict):
                continue
            enabled = bool(pack.get("enabled", True))
            price = int(pack.get("price", 0))
            name = str(pack.get("name", key))
            status = e("enabled", data) if enabled else e("disabled", data)
            label = f"{name} • {status} • {e('coin', data)} {price}"
            if token and token not in label.lower() and token not in str(key).lower():
                continue
            out.append(app_commands.Choice(name=label[:100], value=name))
            if len(out) >= 25:
                break
        return out

    @app_commands.command(name="shop", description="Show enabled packs and their drop-rate tables.")
    async def shop(self, interaction: discord.Interaction) -> None:
        data = self.bot.storage.load()
        ensure_packs_structure(data)
        definitions = data.get("packs", {}).get("definitions", {})
        packs: list[dict[str, Any]] = []
        if isinstance(definitions, dict):
            for key, pack in definitions.items():
                if not isinstance(pack, dict):
                    continue
                if not is_public_shop_pack(str(key), pack):
                    continue
                packs.append({"key": key, **pack})
        view = ShopPages(self, str(interaction.user.id), packs, f"{e('shop', data)} Shop")
        await smart_reply(interaction, embed=view.embed(data), view=view)

    @app_commands.command(name="o_shop_pack_list", description="Owner: list all packs including disabled.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_shop_pack_list(self, interaction: discord.Interaction) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        ensure_packs_structure(data)
        definitions = data.get("packs", {}).get("definitions", {})
        lines: list[str] = []
        if isinstance(definitions, dict):
            for key, pack in definitions.items():
                if not isinstance(pack, dict):
                    continue
                name = str(pack.get("name", key))
                enabled = bool(pack.get("enabled", True))
                status = e("enabled", data) if enabled else e("disabled", data)
                price = int(pack.get("price", 0))
                rates = pack.get("rates", {}) if isinstance(pack.get("rates"), dict) else {}
                short = " ".join(
                    f"{r[0]}{int(rates.get(r, 0))}" for r in ["Common", "Rare", "Epic", "Legendary", "Mythical"] if r in rates
                )
                lines.append(f"{name} • {status} • {e('coin', data)} {price} • {short}")

        view = OwnerPackListPages(self, str(interaction.user.id), lines)
        await smart_reply(interaction, embed=view.embed(data), view=view, ephemeral=True)

    @app_commands.command(name="o_shop_pack_set_enabled", description="Owner: enable/disable a pack.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_shop_pack_set_enabled(self, interaction: discord.Interaction, pack_name: str, enabled: bool) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(d: dict[str, Any]):
            ensure_packs_structure(d)
            key, pack = get_pack_by_name(d, pack_name)
            if not key or not isinstance(pack, dict):
                return False, "pack_not_found", None
            pack["enabled"] = bool(enabled)
            return True, "ok", pack

        ok, reason, pack = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Update Failed", str(reason)), ephemeral=True)
            return

        status = e("enabled", data) if bool(pack.get("enabled", True)) else e("disabled", data)
        await smart_reply(interaction, 
            embed=make_embed(data, f"{e('ok', data)} Pack Visibility Updated", f"{pack.get('name')} • {status}"),
            ephemeral=True,
        )

    @o_shop_pack_set_enabled.autocomplete("pack_name")
    async def o_shop_pack_set_enabled_pack_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return self._pack_choices(self.bot.storage.load(), current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
