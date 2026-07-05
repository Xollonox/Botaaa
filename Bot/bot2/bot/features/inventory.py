"""Inventory/collection premium gallery, detail, and star-upgrade commands."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import compute_power, compute_scaled_stats, find_catalog_card, get_flat_stat_bonus, normalize_mastery_list, rarity_rank
from bot.utils.checks import ensure_registered
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.utils.ui import e, make_embed, simple_embed

PAGE_SIZE = 25
SEPARATOR = "━" * 20
FILTER_OPTIONS = ["All Fighters", "Legendary", "Epic", "Rare", "Favorites", "Locked", "Unlocked"]
SORT_OPTIONS = ["Power Desc", "Power Asc", "Stars", "Name", "Newest"]
UPGRADE_BASE_COSTS = {
    "Common":    500,
    "Rare":      1200,
    "Epic":      3000,
    "Legendary": 6000,
    "Mythical":  9000,
    "Infernal":  14000,
    "Abyssal":   20000,
}


def _make_bar(percent: float, slots: int = 10) -> str:
    percent = max(0, min(100, percent))
    filled = round(percent / 100 * slots)
    return "█" * filled + "░" * (slots - filled)


def _clamp_stars(stars: Any) -> int:
    return max(0, min(5, int(stars or 0)))


def get_star_multiplier(data: dict[str, Any], item: dict[str, Any], stars: int) -> float:
    card_def = _get_card_def(data, item)
    if not card_def:
        return 1.0
    base = compute_power(compute_scaled_stats(card_def, 0))
    if base <= 0:
        return 1.0
    return compute_power(compute_scaled_stats(card_def, _clamp_stars(stars))) / base


def _is_favorite(item: dict[str, Any]) -> bool:
    return bool(item.get("favorite", item.get("favourite", False)))


def _get_card_def(data: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    catalog = data.get("cards", {})
    if not isinstance(catalog, dict):
        return {}
    card_name = str(item.get("card_name", item.get("name", "")))
    card = find_catalog_card(catalog, card_name)
    return card if isinstance(card, dict) else {}


def _compute_item_power(data: dict[str, Any], item: dict[str, Any], stars_override: int | None = None) -> int:
    card_def = _get_card_def(data, item)
    stars = _clamp_stars(item.get("stars", 0) if stars_override is None else stars_override)
    return compute_power(compute_scaled_stats(card_def, stars)) if card_def else 0


def _rarity_emoji(data: dict[str, Any], rarity: str) -> str:
    key = str(rarity).lower()
    value = e(key, data)
    return value if value and value != key else e("card", data)


def _upgrade_cost(item: dict[str, Any]) -> int:
    rarity = str(item.get("rarity", "Common"))
    base = int(UPGRADE_BASE_COSTS.get(rarity, 500))
    stars = _clamp_stars(item.get("stars", 0))
    return int(round(base * (1.6 ** stars)))


def _effective_stats(data: dict[str, Any], item: dict[str, Any], stars_override: int | None = None) -> dict[str, int]:
    card_def = _get_card_def(data, item)
    stars = _clamp_stars(item.get("stars", 0) if stars_override is None else stars_override)
    scaled = compute_scaled_stats(card_def, stars)
    hp = max(100, compute_power(scaled) // 5 + 100)
    return {
        "hp":         hp,
        "strength":   int(scaled.get("strength", 0)),
        "speed":      int(scaled.get("speed", 0)),
        "endurance":  int(scaled.get("endurance", 0)),
        "technique":  int(scaled.get("technique", 0)),
        "iq":         int(scaled.get("iq", 0)),
        "battle_iq":  int(scaled.get("battle_iq", 0)),
    }




def _star_string(stars: int) -> str:
    stars = _clamp_stars(stars)
    return "★" * stars + "☆" * (5 - stars)


def _rarity_icon(rarity: str) -> str:
    from bot.data.constants import rarity_icon
    return rarity_icon(str(rarity).title()) or "⚪"

def _sanitize_view(view: discord.ui.View) -> None:
    for i, child in enumerate(view.children):
        if isinstance(child, discord.ui.Button):
            has_label = isinstance(child.label, str) and child.label.strip()
            if not has_label and child.emoji is None:
                child.label = f"Action {i + 1}"
            elif not has_label and child.emoji is not None:
                child.label = f"Action {i + 1}"
        elif isinstance(child, discord.ui.Select):
            if not isinstance(child.placeholder, str) or not child.placeholder.strip():
                child.placeholder = "Select an option"
            fixed: list[discord.SelectOption] = []
            for j, opt in enumerate(child.options[:25]):
                label = (str(getattr(opt, "label", "") or "").strip() or f"Option {j + 1}")[:100]
                value = str(getattr(opt, "value", "") or "").strip() or f"option_{j + 1}"
                description = getattr(opt, "description", None)
                if isinstance(description, str):
                    description = description[:100]
                fixed.append(discord.SelectOption(
                    label=label,
                    value=value,
                    description=description,
                    emoji=getattr(opt, "emoji", None),
                    default=getattr(opt, "default", False),
                ))
            if fixed:
                child.options = fixed


class UpgradeConfirmView(discord.ui.View):
    def __init__(self, cog: "InventoryCog", invoker_id: int, uid: str, detail_view: "CollectionDetailView") -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.invoker_id = invoker_id
        self.uid = uid
        self.detail_view = detail_view
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await smart_reply(interaction, "This upgrade panel belongs to another player.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="✅ Confirm Upgrade", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        status, stars, coins = self.cog._perform_upgrade(str(interaction.user.id), self.uid)
        data = self.cog.bot.storage.load()
        sep = e("line", data)

        if status == "need_duplicate":
            await smart_reply(interaction, "⚠ You need another copy of this fighter to upgrade.", ephemeral=True)
            return
        if status == "maxed":
            await smart_reply(
                interaction,
                embed=make_embed(data, "⭐ Already at Max Stars", "This card is already at **5★** and cannot be upgraded further."),
                ephemeral=True,
            )
            return
        if status == "not_enough":
            item = self.cog._find_item(data, str(interaction.user.id), self.uid)
            needed = _upgrade_cost(item) if item else 0
            await smart_reply(
                interaction,
                embed=make_embed(
                    data,
                    f"{e('warning', data)} Insufficient Coins",
                    f"You need **{needed:,}** coins but only have **{coins:,}**.",
                ),
                ephemeral=True,
            )
            return
        if status != "ok":
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Upgrade Failed", "Card not found in your inventory."),
                ephemeral=True,
            )
            return

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        item = self.cog._find_item(data, str(interaction.user.id), self.uid)
        name = str(item.get("card_name", item.get("name", "Card"))) if item else "Card"
        now_stats = _effective_stats(data, item or {}, stars_override=stars)
        mult = get_star_multiplier(data, item, stars)

        embed = make_embed(
            data,
            f"⭐ Upgrade Successful!",
            f"{sep * 3}\n**{name}** is now **{stars}★** (×{mult:.2f} stat multiplier)\n{sep * 3}",
            fields=[
                (
                    "📊 Updated Stats",
                    (
                        f"❤️ HP: **{now_stats['hp']:,}**\n"
                        f"💪 STR: **{now_stats['strength']:,}**\n"
                        f"⚡ SPD: **{now_stats['speed']:,}**\n"
                        f"🛡 END: **{now_stats['endurance']:,}**\n"
                        f"🎯 TEC: **{now_stats['technique']:,}**\n"
                        f"🧠 IQ: **{now_stats['iq']:,}**\n"
                        f"🔮 BIQ: **{now_stats['battle_iq']:,}**"
                    ),
                    True,
                ),
                (f"{e('coin', data)} Remaining Coins", f"**{coins:,}**", True),
            ],
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        data = self.cog.bot.storage.load()
        await interaction.response.edit_message(
            embed=make_embed(data, f"{e('info', data)} Upgrade Cancelled", "No changes were made to this card."),
            view=self,
        )


class CollectionDetailView(discord.ui.View):
    def __init__(
        self,
        cog: "InventoryCog",
        invoker_id: int,
        card_uid: str,
        filter_value: str,
        sort_value: str,
        page: int,
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.invoker_id = invoker_id
        self.card_uid = card_uid
        self.filter_value = filter_value
        self.sort_value = sort_value
        self.page = page
        self.message: discord.Message | None = None

    def _entries(self, interaction: discord.Interaction) -> list[dict[str, Any]]:
        data = self.cog.bot.storage.load()
        return self.cog._get_entries(data, str(interaction.user.id), self.filter_value, self.sort_value)

    def _mode(self, data: dict[str, Any], user_id: str) -> str:
        item = self.cog._find_item(data, user_id, self.card_uid)
        card_def = _get_card_def(data, item or {}) if item else {}
        has_path = bool(str(card_def.get("unique_path", "")).strip())
        has_skill = bool(str(card_def.get("unique_skill", "")).strip())
        return "fighter" if (has_path or has_skill) else "viewer"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await smart_reply(interaction, "This collection panel belongs to another player.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        entries = self.cog._get_entries(data, str(interaction.user.id), self.filter_value, self.sort_value)
        if not entries:
            return
        uids = [str(x.get("uid", "")) for x in entries if isinstance(x, dict)]
        if self.card_uid not in uids:
            self.card_uid = uids[0]
        else:
            idx = uids.index(self.card_uid)
            self.card_uid = uids[(idx - 1) % len(uids)]

        mode = self._mode(data, str(interaction.user.id))
        embed = self.cog._build_card_view_embed(data, str(interaction.user.id), self.card_uid, mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, row=0)
    async def next_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        entries = self.cog._get_entries(data, str(interaction.user.id), self.filter_value, self.sort_value)
        if not entries:
            return
        uids = [str(x.get("uid", "")) for x in entries if isinstance(x, dict)]
        if self.card_uid not in uids:
            self.card_uid = uids[0]
        else:
            idx = uids.index(self.card_uid)
            self.card_uid = uids[(idx + 1) % len(uids)]

        mode = self._mode(data, str(interaction.user.id))
        embed = self.cog._build_card_view_embed(data, str(interaction.user.id), self.card_uid, mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Lock / Unlock", style=discord.ButtonStyle.secondary, row=1)
    async def lock_toggle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        status = self.cog._toggle_lock(str(interaction.user.id), self.card_uid)
        data = self.cog.bot.storage.load()
        if status != "ok":
            await smart_reply(interaction, "Unable to update lock state.", ephemeral=True)
            return
        mode = self._mode(data, str(interaction.user.id))
        embed = self.cog._build_card_view_embed(data, str(interaction.user.id), self.card_uid, mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Favorite", style=discord.ButtonStyle.primary, row=1)
    async def favorite_toggle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        status = self.cog._toggle_favorite(str(interaction.user.id), self.card_uid)
        data = self.cog.bot.storage.load()
        if status != "ok":
            await smart_reply(interaction, "Unable to update favorite state.", ephemeral=True)
            return
        mode = self._mode(data, str(interaction.user.id))
        embed = self.cog._build_card_view_embed(data, str(interaction.user.id), self.card_uid, mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Upgrade", style=discord.ButtonStyle.success, row=1)
    async def upgrade(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        item = self.cog._find_item(data, str(interaction.user.id), self.card_uid)
        if item is None:
            await smart_reply(interaction, "Card not found.", ephemeral=True)
            return

        inv = data.get("players", {}).get(str(interaction.user.id), {}).get("user", {}).get("inventory", [])
        if not isinstance(inv, list):
            inv = []
        same = [x for x in inv if isinstance(x, dict) and str(x.get("card_name", "")) == str(item.get("card_name", "")) and str(x.get("uid", "")) != str(item.get("uid", ""))]
        if len(same) < 1:
            await smart_reply(interaction, "⚠ You need another copy of this fighter to upgrade.", ephemeral=True)
            return

        preview = self.cog._build_upgrade_preview_embed(data, item)
        view = UpgradeConfirmView(self.cog, self.invoker_id, self.card_uid, self)
        _sanitize_view(view)
        await interaction.response.edit_message(embed=preview, view=view)
        view.message = interaction.message

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_to_collection(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        entries = self.cog._get_entries(data, str(interaction.user.id), self.filter_value, self.sort_value)
        view = CollectionGalleryView(self.cog, self.invoker_id, self.filter_value, self.sort_value, self.page)
        embed = view.build_embed(data, entries)
        _sanitize_view(view)
        await interaction.response.edit_message(embed=embed, view=view)
        view.message = interaction.message


class FilterSelect(discord.ui.Select):
    def __init__(self, view: "CollectionGalleryView") -> None:
        options = [
            discord.SelectOption(label=label[:100], value=label, default=(label == view.filter_value))
            for label in FILTER_OPTIONS
        ]
        super().__init__(placeholder="Filter Fighters", min_values=1, max_values=1, options=options, row=0)
        self.collection_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.collection_view.invoker_id:
            await interaction.response.send_message("This collection panel belongs to another player.", ephemeral=True)
            return
        self.collection_view.filter_value = self.values[0]
        self.collection_view.page = 1
        data = self.collection_view.cog.bot.storage.load()
        entries = self.collection_view.cog._get_entries(data, str(interaction.user.id), self.collection_view.filter_value, self.collection_view.sort_value)
        self.collection_view.sync_state(entries)
        _sanitize_view(self.collection_view)
        await interaction.response.edit_message(embed=self.collection_view.build_embed(data, entries), view=self.collection_view)


class SortSelect(discord.ui.Select):
    def __init__(self, view: "CollectionGalleryView") -> None:
        options = [
            discord.SelectOption(label=label[:100], value=label, default=(label == view.sort_value))
            for label in SORT_OPTIONS
        ]
        super().__init__(placeholder="Sort Fighters", min_values=1, max_values=1, options=options, row=1)
        self.collection_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.collection_view.invoker_id:
            await interaction.response.send_message("This collection panel belongs to another player.", ephemeral=True)
            return
        self.collection_view.sort_value = self.values[0]
        self.collection_view.page = 1
        data = self.collection_view.cog.bot.storage.load()
        entries = self.collection_view.cog._get_entries(data, str(interaction.user.id), self.collection_view.filter_value, self.collection_view.sort_value)
        self.collection_view.sync_state(entries)
        _sanitize_view(self.collection_view)
        await interaction.response.edit_message(embed=self.collection_view.build_embed(data, entries), view=self.collection_view)


class CardSelectMenu(discord.ui.Select):
    def __init__(self, view: "CollectionGalleryView", entries: list[dict[str, Any]]) -> None:
        page = view.page
        start = (page - 1) * PAGE_SIZE
        current = entries[start:start + PAGE_SIZE]

        options: list[discord.SelectOption] = []
        for item in current:
            if not isinstance(item, dict):
                continue
            name = str(item.get("card_name", item.get("name", "Unknown"))).strip()
            uid = str(item.get("uid", "")).strip()
            rarity = str(item.get("rarity", "Common"))
            stars = _clamp_stars(item.get("stars", 0))
            icon = _rarity_icon(rarity)
            star_str = "★" * stars if stars else ""
            label = f"{icon} {name}"[:100]
            description = f"{rarity}{' · ' + star_str if star_str else ''}"[:100]
            options.append(discord.SelectOption(label=label, value=uid, description=description))

        if not options:
            options = [discord.SelectOption(label="No cards on this page", value="__none__")]

        super().__init__(
            placeholder="🃏 Select a fighter to view...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=2,
        )
        self.gallery_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.gallery_view.invoker_id:
            await interaction.response.send_message("This collection panel belongs to another player.", ephemeral=True)
            return
        uid = self.values[0]
        if uid == "__none__":
            await interaction.response.defer()
            return
        data = self.gallery_view.cog.bot.storage.load()
        item = self.gallery_view.cog._find_item(data, str(interaction.user.id), uid)
        card_def = _get_card_def(data, item or {}) if item else {}
        has_path = bool(str(card_def.get("unique_path", "")).strip())
        has_skill = bool(str(card_def.get("unique_skill", "")).strip())
        mode = "fighter" if (has_path or has_skill) else "viewer"
        embed = self.gallery_view.cog._build_card_view_embed(data, str(interaction.user.id), uid, mode)
        detail_view = CollectionDetailView(self.gallery_view.cog, interaction.user.id, uid, self.gallery_view.filter_value, self.gallery_view.sort_value, self.gallery_view.page)
        _sanitize_view(detail_view)
        await interaction.response.edit_message(embed=embed, view=detail_view)
        detail_view.message = interaction.message


class CollectionGalleryView(discord.ui.View):
    def __init__(self, cog: "InventoryCog", invoker_id: int, filter_value: str = "All Fighters", sort_value: str = "Power Desc", page: int = 1) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.invoker_id = invoker_id
        self.filter_value = filter_value
        self.sort_value = sort_value
        self.page = max(1, page)
        self.total_pages = 1
        self.message: discord.Message | None = None

        self.filter_select = FilterSelect(self)
        self.sort_select = SortSelect(self)
        self.add_item(self.filter_select)
        self.add_item(self.sort_select)

        self.prev_button = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=3)
        self.next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary, row=3)
        self.prev_button.callback = self._on_prev
        self.next_button.callback = self._on_next
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    def sync_state(self, entries: list[dict[str, Any]]) -> None:
        self.total_pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(1, min(self.page, self.total_pages))
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

    def _refresh_card_buttons(self, entries: list[dict[str, Any]]) -> None:
        for child in list(self.children):
            if isinstance(child, CardSelectMenu):
                self.remove_item(child)
        self.add_item(CardSelectMenu(self, entries))

    def build_embed(self, data: dict[str, Any], entries: list[dict[str, Any]]) -> discord.Embed:
        self.sync_state(entries)
        self._refresh_card_buttons(entries)

        catalog = data.get("cards", {})
        total = len(catalog) if isinstance(catalog, dict) else 0
        inv = data.get("players", {}).get(str(self.invoker_id), {}).get("user", {}).get("inventory", [])
        unique_owned = {
            str(item.get("card_name", item.get("name", "")))
            for item in inv
            if isinstance(item, dict) and str(item.get("card_name", item.get("name", "")))
        }
        owned = len(inv) if isinstance(inv, list) else 0
        completion = (len(unique_owned) / max(1, total) * 100.0) if total else 0.0

        body = (
            "╭─ Progress\n"
            f"│ 📦 Cards Owned: {owned}\n"
            f"│ 🃏 Unique Fighters: {len(unique_owned)}/{total}\n"
            "│ 📊 Completion\n"
            f"│ {_make_bar(completion)} {completion:.0f}%\n"
            "╰────────────────\n\n"
            "Select a fighter below to view."
        )
        embed = make_embed(None, "LOOKISM HXCC • COLLECTION", body, color=0xE11D48, footer=f"Card Collection • Page {self.page}/{self.total_pages}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await smart_reply(interaction, "This collection panel belongs to another player.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        data = self.cog.bot.storage.load()
        entries = self.cog._get_entries(data, str(interaction.user.id), self.filter_value, self.sort_value)
        _sanitize_view(self)
        await interaction.response.edit_message(embed=self.build_embed(data, entries), view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        self.page += 1
        data = self.cog.bot.storage.load()
        entries = self.cog._get_entries(data, str(interaction.user.id), self.filter_value, self.sort_value)
        _sanitize_view(self)
        await interaction.response.edit_message(embed=self.build_embed(data, entries), view=self)


class InventoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _ensure_inventory_defaults(self, user_id: str) -> None:
        def mutate(data: dict[str, Any]) -> None:
            inv = data.get("players", {}).get(user_id, {}).get("user", {}).get("inventory", [])
            if not isinstance(inv, list):
                return
            for item in inv:
                if not isinstance(item, dict):
                    continue
                if "stars" not in item:
                    item["stars"] = 0
                item["stars"] = _clamp_stars(item.get("stars", 0))
                if "name" not in item and "card_name" in item:
                    item["name"] = item.get("card_name", "")
                if "favourite" not in item and "favorite" in item:
                    item["favourite"] = bool(item.get("favorite", False))
                if "favorite" not in item and "favourite" in item:
                    item["favorite"] = bool(item.get("favourite", False))

        self.bot.storage.with_lock(mutate)

    def _get_entries(self, data: dict[str, Any], user_id: str, filter_value: str, sort_value: str) -> list[dict[str, Any]]:
        inventory = data.get("players", {}).get(user_id, {}).get("user", {}).get("inventory", [])
        if not isinstance(inventory, list):
            return []

        filtered: list[dict[str, Any]] = []
        for item in inventory:
            if not isinstance(item, dict):
                continue
            rarity = str(item.get("rarity", "Common"))
            locked = bool(item.get("market_locked", False) or item.get("squad_locked", False) or item.get("locked", False))
            fav = _is_favorite(item)

            include = False
            if filter_value == "All Fighters":
                include = True
            elif filter_value == "Favorites":
                include = fav
            elif filter_value == "Locked":
                include = locked
            elif filter_value == "Unlocked":
                include = not locked
            else:
                include = rarity.lower() == filter_value.lower()

            if include:
                filtered.append(item)

        if sort_value == "Power Desc":
            filtered.sort(key=lambda x: (-_compute_item_power(data, x), -_clamp_stars(x.get("stars", 0)), str(x.get("card_name", "")).lower()))
        elif sort_value == "Power Asc":
            filtered.sort(key=lambda x: (_compute_item_power(data, x), _clamp_stars(x.get("stars", 0)), str(x.get("card_name", "")).lower()))
        elif sort_value == "Stars":
            filtered.sort(key=lambda x: (-_clamp_stars(x.get("stars", 0)), -rarity_rank(str(x.get("rarity", "Common"))), str(x.get("card_name", "")).lower()))
        elif sort_value == "Newest":
            filtered.sort(key=lambda x: -int(x.get("acquired_at", 0) or 0))
        else:
            filtered.sort(key=lambda x: str(x.get("card_name", x.get("name", ""))).lower())
        return filtered


    def _find_item(self, data: dict[str, Any], user_id: str, uid_or_name: str) -> dict[str, Any] | None:
        inv = data.get("players", {}).get(user_id, {}).get("user", {}).get("inventory", [])
        if not isinstance(inv, list):
            return None

        q = uid_or_name.strip()
        for item in inv:
            if isinstance(item, dict) and str(item.get("uid", "")) == q:
                return item

        ql = q.lower()
        for item in inv:
            if not isinstance(item, dict):
                continue
            name = str(item.get("card_name", item.get("name", ""))).lower()
            if name == ql or ql in name:
                return item
        return None

    def _build_upgrade_preview_embed(self, data: dict[str, Any], item: dict[str, Any]) -> discord.Embed:
        stars = _clamp_stars(item.get("stars", 0))
        next_stars = min(5, stars + 1)
        cur_mult = get_star_multiplier(data, item, stars)
        nxt_mult = get_star_multiplier(data, item, next_stars)

        cur_stats = _effective_stats(data, item, stars_override=stars)
        nxt_stats = _effective_stats(data, item, stars_override=next_stars)
        cost = _upgrade_cost(item)
        card_name = str(item.get("card_name", item.get("name", "Card")))

        body = (
            "**UPGRADE PREVIEW**\n\n"
            f"{card_name}\n\n"
            "╭─ Star Evolution\n"
            f"│ {_star_string(stars)} → {_star_string(next_stars)}\n"
            f"│ Multiplier: {cur_mult:.2f} → {nxt_mult:.2f}\n"
            "╰────────────────\n"
            "╭─ Stat Increase\n"
            f"│ STR {cur_stats['strength']} → {nxt_stats['strength']}\n"
            f"│ SPD {cur_stats['speed']} → {nxt_stats['speed']}\n"
            f"│ END {cur_stats['endurance']} → {nxt_stats['endurance']}\n"
            f"│ TEC {cur_stats['technique']} → {nxt_stats['technique']}\n"
            f"│ IQ {cur_stats['iq']} → {nxt_stats['iq']}\n"
            f"│ BIQ {cur_stats['battle_iq']} → {nxt_stats['battle_iq']}\n"
            "╰────────────────\n"
            "╭─ Requirements\n"
            "│ 🃏 Duplicate Card: 1\n"
            f"│ 💰 Coins: {cost:,}\n"
            "╰────────────────"
        )
        embed = make_embed(None, "LOOKISM HXCC • UPGRADE", body, color=0xE11D48, footer="Star Upgrade")
        return embed

    def _build_card_view_embed(self, data: dict[str, Any], user_id: str, uid: str, mode: str) -> discord.Embed:
        item = self._find_item(data, user_id, uid)
        if item is None:
            embed = make_embed(None, "LOOKISM HXCC • FIGHTER", "Card not found.", color=0xE11D48, footer="Card Collection")
            return embed

        stars = _clamp_stars(item.get("stars", 0))
        card_name = str(item.get("card_name", item.get("name", "Unknown")))
        rarity = str(item.get("rarity", "Common"))
        card_def = _get_card_def(data, item)
        image_url = str(card_def.get("image_url", "")).strip() if isinstance(card_def, dict) else ""
        power = _compute_item_power(data, item, stars_override=stars)

        if mode == "viewer":
            body = (
                f"{card_name} {_star_string(stars)}\n"
                f"⚡ Power: {power:,}"
            )
            embed = make_embed(None, "LOOKISM HXCC • FIGHTER", body, color=0xE11D48, image_url=image_url, footer="Card Collection")
            return embed

        stats = _effective_stats(data, item, stars_override=stars)
        locked = bool(item.get("locked", False) or item.get("market_locked", False) or item.get("squad_locked", False))
        title = str(card_def.get("title", "")).strip() if isinstance(card_def, dict) else ""
        bio = str(card_def.get("description", "")).strip() if isinstance(card_def, dict) else ""
        def _resolve_field(raw: Any, desc_raw: Any = None) -> tuple[str, str]:
            """Handle both plain-string and dict-stored skill/path fields."""
            if isinstance(raw, dict):
                name = str(raw.get("name", raw.get("title", "—"))).strip() or "—"
                desc = str(raw.get("description", raw.get("desc", ""))).strip() or "—"
                return name, desc
            name = str(raw or "").strip() or "—"
            desc = str(desc_raw or "").strip() or "—"
            return name, desc

        unique_path, unique_path_desc = _resolve_field(
            card_def.get("unique_path"), card_def.get("unique_path_description")
        )
        unique_skill, unique_skill_desc = _resolve_field(
            card_def.get("unique_skill"), card_def.get("unique_skill_description")
        )
        unique_skill_2, unique_skill_2_desc = _resolve_field(card_def.get("unique_skill_2"))
        unique_skill_3, unique_skill_3_desc = _resolve_field(card_def.get("unique_skill_3"))
        mastery_list: list[str] = normalize_mastery_list(card_def.get("mastery", []) if isinstance(card_def, dict) else [])
        mastery_str = "  ".join(f"• {m}" for m in mastery_list) if mastery_list else "—"

        # Compute skill unlock thresholds
        skill_count = sum([
            bool(card_def.get("unique_skill")),
            bool(card_def.get("unique_skill_2")),
            bool(card_def.get("unique_skill_3")),
        ])
        _skill_thresholds = {1: [3], 2: [3, 4], 3: [3, 4, 5]}.get(skill_count, [])

        def _skill_block(skill_name: str, skill_desc: str, skill_raw: Any, unlock_star: int | None) -> str:
            kind = ""
            if isinstance(skill_raw, dict):
                kind = " [Active]" if skill_raw.get("active", True) else " [Passive]"
            if unlock_star is not None and stars < unlock_star:
                return (
                    f"╭─ Unique Skill{kind}\n"
                    f"│ 🔒 Unlocks at ★{unlock_star}\n"
                    "╰────────────────\n\n"
                )
            return (
                f"╭─ Unique Skill{kind}\n"
                f"│ {skill_name}\n"
                f"│ {skill_desc}\n"
                "╰────────────────\n\n"
            )

        skill_blocks = ""
        if skill_count >= 1:
            skill_blocks += _skill_block(unique_skill, unique_skill_desc, card_def.get("unique_skill"), _skill_thresholds[0] if _skill_thresholds else None)
        if skill_count >= 2:
            skill_blocks += _skill_block(unique_skill_2, unique_skill_2_desc, card_def.get("unique_skill_2"), _skill_thresholds[1] if len(_skill_thresholds) > 1 else None)
        if skill_count >= 3:
            skill_blocks += _skill_block(unique_skill_3, unique_skill_3_desc, card_def.get("unique_skill_3"), _skill_thresholds[2] if len(_skill_thresholds) > 2 else None)

        path_raw = card_def.get("unique_path")
        path_kind = ""
        if isinstance(path_raw, dict):
            path_kind = " [Active]" if path_raw.get("active", True) else " [Passive]"
        if path_raw and stars < 5:
            path_block = (
                f"╭─ Unique Path{path_kind}\n"
                "│ 🔒 Unlocks at ★5\n"
                "╰────────────────\n\n"
            )
        elif path_raw:
            path_block = (
                f"╭─ Unique Path{path_kind}\n"
                f"│ {unique_path}\n"
                f"│ {unique_path_desc}\n"
                "╰────────────────\n\n"
            )
        else:
            path_block = ""

        # Weapon slot
        weapon_uid = item.get("weapon_uid")
        weapon_line = ""
        if card_def.get("weapon_user", False):
            if weapon_uid:
                p = data.get("players", {}).get(user_id, {})
                w_inv = p.get("user", {}).get("weapon_inventory", []) if isinstance(p, dict) else []
                equipped_w = next((w for w in w_inv if isinstance(w, dict) and str(w.get("uid", "")) == weapon_uid), None)
                weapon_line = f"⚔️ Weapon: {equipped_w.get('weapon_name', '?')} {_star_string(int(equipped_w.get('stars', 0)))}\n" if equipped_w else "⚔️ Weapon: —\n"
            else:
                weapon_line = "⚔️ Weapon: —\n"

        heading = f"{_rarity_icon(rarity)} {rarity} • {card_name}"
        if title:
            heading += f"\n{title}"

        body = (
            f"{heading}\n\n"
            "╭─ Bio\n"
            f"│ {bio or '—'}\n"
            "╰────────────────\n\n"
            "╭─ Combat Stats\n"
            f"│ 💪 STR: {stats['strength']}\n"
            f"│ ⚡ SPD: {stats['speed']}\n"
            f"│ 🛡 END: {stats['endurance']}\n"
            f"│ 🎯 TEC: {stats['technique']}\n"
            f"│ 🧠 IQ: {stats['iq']}\n"
            f"│ 🔮 BIQ: {stats['battle_iq']}\n"
            "╰────────────────\n\n"
            "╭─ Progression\n"
            f"│ ⭐ Stars: {_star_string(stars)}\n"
            f"│ ⚡ Power: {power:,}\n"
            f"│ {'🔒 Status: Locked' if locked else '🔓 Status: Unlocked'}\n"
            f"│ {weapon_line}"
            "╰────────────────\n\n"
            "╭─ Mastery\n"
            f"│ {mastery_str}\n"
            "╰────────────────\n\n"
            + skill_blocks + path_block
        ).rstrip()
        embed = make_embed(None, "LOOKISM HXCC • FIGHTER", body, color=0xE11D48, image_url=image_url, footer="Card Collection")
        return embed


    def _toggle_lock(self, user_id: str, uid: str) -> str:
        def mutate(data: dict[str, Any]) -> str:
            item = self._find_item(data, user_id, uid)
            if item is None:
                return "not_found"
            current = bool(item.get("locked", False))
            if current and bool(item.get("squad_locked", False)):
                return "squad_locked"
            item["locked"] = not current
            return "ok"

        return self.bot.storage.with_lock(mutate)

    def _toggle_favorite(self, user_id: str, uid: str) -> str:
        def mutate(data: dict[str, Any]) -> str:
            item = self._find_item(data, user_id, uid)
            if item is None:
                return "not_found"
            value = not _is_favorite(item)
            item["favorite"] = value
            item["favourite"] = value
            return "ok"

        return self.bot.storage.with_lock(mutate)

    def _perform_upgrade(self, user_id: str, uid: str) -> tuple[str, int, int]:
        def mutate(data: dict[str, Any]) -> tuple[str, int, int]:
            player = data["players"].get(user_id, {})
            user = player.get("user", {}) if isinstance(player, dict) else {}
            item = self._find_item(data, user_id, uid)
            if item is None:
                return "not_found", 0, int(user.get("balance", user.get("coins", 0)))

            stars = _clamp_stars(item.get("stars", 0))
            if stars >= 5:
                return "maxed", stars, int(user.get("balance", user.get("coins", 0)))

            cost = _upgrade_cost(item)
            coins = int(user.get("balance", user.get("coins", 0)))
            if coins < cost:
                return "not_enough", stars, coins

            dup_idx = next((i for i, row in enumerate(user.get("inventory", [])) if isinstance(row, dict) and str(row.get("card_name", "")) == str(item.get("card_name", "")) and str(row.get("uid", "")) != str(item.get("uid", "")) and not bool(row.get("squad_locked", False) or row.get("market_locked", False) or row.get("locked", False) or row.get("trade_locked", False) or row.get("weapon_uid"))), -1)
            if dup_idx < 0:
                return "need_duplicate", stars, coins

            user["balance"] = coins - cost
            if "coins" in user:
                user["coins"] = user["balance"]
            user["inventory"].pop(dup_idx)
            item["stars"] = stars + 1
            return "ok", stars + 1, int(user.get("balance", user.get("coins", 0)))

        return self.bot.storage.with_lock(mutate)

    @app_commands.command(name="collection", description="Browse your card collection.")
    async def collection(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)
        data = self.bot.storage.load()

        if user_id not in data.get("players", {}):
            await interaction.response.send_message("Could not load your player data. Please try again.", ephemeral=True)
            return

        view = CollectionGalleryView(self, interaction.user.id, "All Fighters", "Power Desc", 1)
        entries = self._get_entries(data, user_id, "All Fighters", "Power Desc")
        embed = view.build_embed(data, entries)
        if not entries:
            await interaction.response.send_message(embed=embed)
            return
        _sanitize_view(view)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InventoryCog(bot))
