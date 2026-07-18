"""Keystone equip/info commands for Mythical+ cards."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import find_catalog_card, find_catalog_key, find_owned_instance
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply

_KEYSTONE_RARITIES = {"Mythical", "Infernal", "Abyssal"}


def _get_keystone_for_card(data: dict[str, Any], card_def: dict[str, Any]) -> dict[str, Any] | None:
    keystone_name = card_def.get("keystone_name")
    if not keystone_name:
        return None
    keystones = data.get("keystones", {})
    key = str(keystone_name).strip().lower()
    return keystones.get(key)


class KeystonesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="keystone_assign", description="Equip or unequip your keystone on a Mythical+ card.")
    async def keystone_assign(self, interaction: discord.Interaction, card_name: str) -> None:
        from bot.utils.checks import ensure_registered
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            player = data.get("players", {}).get(user_id, {})
            inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
            if not isinstance(inv, list):
                return "no_inventory", {}

            instance, _ = find_owned_instance(inv, card_name)
            if instance is None:
                return "not_found", {}

            rarity = str(instance.get("rarity", ""))
            if rarity not in _KEYSTONE_RARITIES:
                return "wrong_rarity", {"rarity": rarity}

            catalog = data.get("cards", {})
            card_def = find_catalog_card(catalog, str(instance.get("card_name", "")))
            if card_def is None:
                return "no_def", {}

            keystone = _get_keystone_for_card(data, card_def)
            if keystone is None:
                return "no_keystone", {"card": str(card_def.get("name", ""))}

            currently_equipped = bool(instance.get("keystone_equipped", False))
            instance["keystone_equipped"] = not currently_equipped
            return "unequipped" if currently_equipped else "equipped", {
                "card": str(card_def.get("name", "")),
                "keystone": str(keystone.get("name", "")),
            }

        result, info = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if result == "equipped":
            body = (
                f"**Keystone Equipped**\n"
                f"Card: {info['card']}\n"
                f"Keystone: {info['keystone']}\n"
            )
            await smart_reply(interaction, embed=make_embed(data, "LOOKISM HXCC • KEYSTONE", body, color=0x9B59B6))
        elif result == "unequipped":
            body = (
                f"**Keystone Unequipped**\n"
                f"Card: {info['card']}\n"
                f"Keystone: {info['keystone']}\n"
            )
            await smart_reply(interaction, embed=make_embed(data, "LOOKISM HXCC • KEYSTONE", body, color=0x95A5A6))
        elif result == "wrong_rarity":
            await error_reply(interaction, f"Keystones are only available for Mythical, Infernal, and Abyssal cards. This card is {info.get('rarity')}.")
        elif result == "no_keystone":
            await error_reply(interaction, f"**{info.get('card')}** does not have a keystone assigned.")
        elif result == "not_found":
            await error_reply(interaction, "No matching owned card found.")
        else:
            await error_reply(interaction, "Could not process request.")

    @app_commands.command(name="keystone_info", description="View the keystone details for one of your Mythical+ cards.")
    async def keystone_info(self, interaction: discord.Interaction, card_name: str) -> None:
        from bot.utils.checks import ensure_registered
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)
        data = self.bot.storage.load()

        player = data.get("players", {}).get(user_id, {})
        inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
        if not isinstance(inv, list):
            await error_reply(interaction, "Inventory unavailable.")
            return

        instance, _ = find_owned_instance(inv, card_name)
        if instance is None:
            await error_reply(interaction, "No matching owned card found.")
            return

        rarity = str(instance.get("rarity", ""))
        if rarity not in _KEYSTONE_RARITIES:
            await error_reply(interaction, f"Keystones are only available for Mythical, Infernal, and Abyssal cards.")
            return

        catalog = data.get("cards", {})
        card_def = find_catalog_card(catalog, str(instance.get("card_name", "")))
        if card_def is None:
            await error_reply(interaction, "Card definition not found.")
            return

        keystone = _get_keystone_for_card(data, card_def)
        if keystone is None:
            await error_reply(interaction, f"**{card_def.get('name')}** does not have a keystone assigned.")
            return

        equipped = bool(instance.get("keystone_equipped", False))
        kind = "Active" if keystone.get("active", True) else "Passive"
        status = "✅ Equipped" if equipped else "❌ Unequipped"

        body = (
            f"**Keystone — {keystone.get('name', '—')}**\n"
            f"Card: {card_def.get('name', '—')}\n"
            f"Type: {kind}\n"
            f"Status: {status}\n"
            "**Effect**\n"
            f"{keystone.get('effect', '—')}\n"
        )
        await smart_reply(interaction, embed=make_embed(data, "LOOKISM HXCC • KEYSTONE", body, color=0x9B59B6))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(KeystonesCog(bot))
