"""Weapon inventory gallery and equip/unequip commands."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.data.constants import rarity_icon, RARITY_RANK
from bot.utils.weapon_logic import (
    build_weapon_instance, get_weapon_buffs,
    equip_weapon, unequip_weapon, upgrade_weapon,
)
from bot.utils.checks import ensure_registered
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.utils.ui import e, make_embed

_PAGE_SIZE = 10


def _star_str(stars: int) -> str:
    s = max(0, min(5, int(stars or 0)))
    return "★" * s + "☆" * (5 - s)


def _rarity_icon(rarity: str) -> str:
    return rarity_icon(str(rarity).title()) or "⚪"


def _weapon_line(w: dict[str, Any]) -> str:
    stars = _star_str(int(w.get("stars", 0)))
    rarity = str(w.get("rarity", ""))
    icon = _rarity_icon(rarity)
    equipped = " [equipped]" if w.get("equipped_to") else ""
    return f"{icon} **{w.get('weapon_name', '?')}** {stars}{equipped}"


class WeaponDetailView(discord.ui.View):
    """Detail view for a single weapon instance."""

    def __init__(
        self,
        bot: commands.Bot,
        user_id: str,
        weapon_uid: str,
        parent_page: int,
    ) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.weapon_uid = weapon_uid
        self.parent_page = parent_page

    def _build_embed(self, data: dict[str, Any]) -> discord.Embed:
        player = data.get("players", {}).get(self.user_id, {})
        weapon_inv = player.get("user", {}).get("weapon_inventory", []) if isinstance(player, dict) else []
        weapon = next((w for w in weapon_inv if isinstance(w, dict) and str(w.get("uid", "")) == self.weapon_uid), None)
        if weapon is None:
            return make_embed(data, "LOOKISM HXCC • WEAPON", "Weapon not found.", color=0xE74C3C)

        weapons_catalog = data.get("weapons", {})
        weapon_name = str(weapon.get("weapon_name", "")).lower()
        weapon_def = weapons_catalog.get(weapon_name) or {}

        stars = int(weapon.get("stars", 0))
        rarity = str(weapon.get("rarity", ""))
        buffs = get_weapon_buffs(weapon, weapons_catalog)
        compatible = weapon_def.get("compatible_cards", [])
        effect = str(weapon_def.get("effect", "—"))
        kind = "Active" if weapon_def.get("effect_active", True) else "Passive"
        image_url = str(weapon_def.get("image_url", ""))

        equipped_to = weapon.get("equipped_to")
        equip_line = "Not equipped"
        if equipped_to:
            card_inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
            card = next((c for c in card_inv if isinstance(c, dict) and str(c.get("uid", "")) == equipped_to), None)
            equip_line = str(card.get("card_name", "Unknown")) if card else "Unknown card"

        buff_lines = "\n".join(
            f"│ +{v} {k.upper()}" for k, v in buffs.items() if v != 0
        ) or "│ No stat buffs"

        body = (
            f"╭─ {_rarity_icon(rarity)} {weapon.get('weapon_name', '?')} [{rarity}]\n"
            f"│ Stars: {_star_str(stars)}\n"
            f"│ Equipped: {equip_line}\n"
            "├─ Stat Buffs (at current stars)\n"
            f"{buff_lines}\n"
            f"├─ Effect [{kind}]\n"
            f"│ {effect}\n"
            f"├─ Compatible Cards\n"
            f"│ {', '.join(compatible) if compatible else '—'}\n"
            "╰────────────────"
        )
        return make_embed(data, "LOOKISM HXCC • WEAPON", body, color=0xE67E22, image_url=image_url)

    @discord.ui.button(label="Equip", style=discord.ButtonStyle.green, custom_id="weapon_equip")
    async def equip_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        data = self.bot.storage.load()
        player = data.get("players", {}).get(self.user_id, {})
        card_inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
        weapons_catalog = data.get("weapons", {})

        weapon_inv = player.get("user", {}).get("weapon_inventory", []) if isinstance(player, dict) else []
        weapon = next((w for w in weapon_inv if isinstance(w, dict) and str(w.get("uid", "")) == self.weapon_uid), None)
        if weapon is None:
            await error_reply(interaction, "Weapon not found.")
            return

        weapon_name = str(weapon.get("weapon_name", "")).lower()
        weapon_def = weapons_catalog.get(weapon_name) or {}
        compatible = [str(c).lower() for c in weapon_def.get("compatible_cards", [])]

        eligible = [
            c for c in card_inv
            if isinstance(c, dict)
            and not c.get("weapon_uid")
            and (not compatible or str(c.get("card_name", "")).lower() in compatible)
        ]

        if not eligible:
            await interaction.response.send_message(
                "No compatible weapon-user cards without a weapon equipped.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=str(c.get("card_name", "?"))[:100],
                value=str(c.get("uid", "")),
                description=f"{c.get('rarity', '')} {_star_str(int(c.get('stars', 0)))}",
            )
            for c in eligible[:25]
        ]

        select = discord.ui.Select(placeholder="Choose a card to equip to", options=options)

        async def on_select(sel_interaction: discord.Interaction) -> None:
            card_uid = sel_interaction.data["values"][0]

            def mutate(d: dict[str, Any]) -> tuple[bool, str]:
                return equip_weapon(d, self.user_id, self.weapon_uid, card_uid)

            ok, msg = self.bot.storage.with_lock(mutate)
            d = self.bot.storage.load()
            if ok:
                await sel_interaction.response.edit_message(
                    embed=self._build_embed(d), view=self,
                )
            else:
                await sel_interaction.response.send_message(msg, ephemeral=True)

        select.callback = on_select
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("Choose a card:", view=v, ephemeral=True)

    @discord.ui.button(label="Unequip", style=discord.ButtonStyle.grey, custom_id="weapon_unequip")
    async def unequip_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return

        def mutate(d: dict[str, Any]) -> tuple[bool, str]:
            return unequip_weapon(d, self.user_id, self.weapon_uid)

        ok, msg = self.bot.storage.with_lock(mutate)
        d = self.bot.storage.load()
        if ok:
            await interaction.response.edit_message(embed=self._build_embed(d), view=self)
        else:
            await error_reply(interaction, msg)

    @discord.ui.button(label="Upgrade", style=discord.ButtonStyle.blurple, custom_id="weapon_upgrade")
    async def upgrade_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return

        def mutate(d: dict[str, Any]) -> tuple[str, int, int]:
            return upgrade_weapon(d, self.user_id, self.weapon_uid)

        result, stars, balance = self.bot.storage.with_lock(mutate)
        d = self.bot.storage.load()

        messages = {
            "ok": lambda: f"Upgraded! Now {_star_str(stars)}. Balance: {balance:,} coins.",
            "maxed": lambda: "Already at 5★.",
            "equipped": lambda: "Unequip the weapon before upgrading.",
            "not_enough": lambda: "Not enough coins.",
            "need_duplicate": lambda: "You need a duplicate weapon to upgrade.",
            "not_found": lambda: "Weapon not found.",
        }
        msg_fn = messages.get(result, lambda: "Could not upgrade.")

        if result == "ok":
            await interaction.response.edit_message(embed=self._build_embed(d), view=self)
            await interaction.followup.send(msg_fn(), ephemeral=True)
        else:
            await interaction.response.send_message(msg_fn(), ephemeral=True)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.grey, custom_id="weapon_back")
    async def back_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        d = self.bot.storage.load()
        gallery = WeaponGalleryView(self.bot, self.user_id, page=self.parent_page)
        await interaction.response.edit_message(embed=gallery.build_embed(d), view=gallery)


class WeaponGalleryView(discord.ui.View):
    """Paginated weapon inventory gallery."""

    def __init__(self, bot: commands.Bot, user_id: str, page: int = 0) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.page = page

    def _get_weapons(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        player = data.get("players", {}).get(self.user_id, {})
        return player.get("user", {}).get("weapon_inventory", []) if isinstance(player, dict) else []

    def build_embed(self, data: dict[str, Any]) -> discord.Embed:
        weapons = self._get_weapons(data)
        total = len(weapons)
        start = self.page * _PAGE_SIZE
        page_weapons = weapons[start: start + _PAGE_SIZE]
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

        if not page_weapons:
            body = "You have no weapons yet.\nWeapons can be obtained from events and weapon packs."
        else:
            lines = [f"{i + 1}. {_weapon_line(w)}" for i, w in enumerate(page_weapons, start=start)]
            body = "\n".join(lines)

        return make_embed(
            data,
            f"LOOKISM HXCC • WEAPONS ({total})",
            body,
            color=0xE67E22,
            footer=f"Page {self.page + 1}/{total_pages} • Select a weapon to view details",
        )

    def _rebuild_select(self, data: dict[str, Any]) -> None:
        # Remove old select if present
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)

        weapons = self._get_weapons(data)
        start = self.page * _PAGE_SIZE
        page_weapons = weapons[start: start + _PAGE_SIZE]
        if not page_weapons:
            return

        options = [
            discord.SelectOption(
                label=w.get("weapon_name", "?")[:100],
                value=str(w.get("uid", "")),
                description=f"{w.get('rarity', '')} {_star_str(int(w.get('stars', 0)))}{'  [equipped]' if w.get('equipped_to') else ''}",
            )
            for w in page_weapons
        ]
        select = discord.ui.Select(placeholder="Select a weapon to inspect", options=options)

        async def on_select(sel_interaction: discord.Interaction) -> None:
            if str(sel_interaction.user.id) != self.user_id:
                await sel_interaction.response.send_message("Not your menu.", ephemeral=True)
                return
            weapon_uid = sel_interaction.data["values"][0]
            d = self.bot.storage.load()
            detail_view = WeaponDetailView(self.bot, self.user_id, weapon_uid, parent_page=self.page)
            await sel_interaction.response.edit_message(embed=detail_view._build_embed(d), view=detail_view)

        select.callback = on_select
        self.add_item(select)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.grey, row=1, custom_id="weapon_prev")
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        d = self.bot.storage.load()
        weapons = self._get_weapons(d)
        total_pages = max(1, (len(weapons) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self.page = (self.page - 1) % total_pages
        self._rebuild_select(d)
        await interaction.response.edit_message(embed=self.build_embed(d), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.grey, row=1, custom_id="weapon_next")
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        d = self.bot.storage.load()
        weapons = self._get_weapons(d)
        total_pages = max(1, (len(weapons) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self.page = (self.page + 1) % total_pages
        self._rebuild_select(d)
        await interaction.response.edit_message(embed=self.build_embed(d), view=self)


class WeaponsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="weapon", description="View and manage your weapon inventory.")
    async def weapon(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)
        data = self.bot.storage.load()
        view = WeaponGalleryView(self.bot, user_id)
        view._rebuild_select(data)
        await smart_reply(interaction, embed=view.build_embed(data), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeaponsCog(bot))
