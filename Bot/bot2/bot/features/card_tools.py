"""Card lookup command for LOOKISM HXCC."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import compute_power, compute_scaled_stats, find_catalog_card, normalize_mastery_list
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply


def _rarity_icon(rarity: str) -> str:
    from bot.data.constants import rarity_icon
    return rarity_icon(str(rarity).title()) or "⚪"


def _resolve_field(raw: Any, desc_raw: Any = None) -> tuple[str, str]:
    """Handle both plain-string and dict-stored skill/path fields."""
    if isinstance(raw, dict):
        name = str(raw.get("name", raw.get("title", "—"))).strip() or "—"
        desc = str(raw.get("description", raw.get("desc", ""))).strip() or "—"
        return name, desc
    name = str(raw or "").strip() or "—"
    desc = str(desc_raw or "").strip() or "—"
    return name, desc


def _resolve_unique_skills(card: dict[str, Any]) -> tuple[str, str]:
    skill_names = card.get("unique_skills")
    if isinstance(skill_names, list):
        names = [str(name).strip() for name in skill_names if str(name).strip()]
        if names:
            return ", ".join(names), "—"
    return _resolve_field(card.get("unique_skill"), card.get("unique_skill_description"))


def _card_name_choices(data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        return []

    token = str(current or "").casefold()
    choices: list[app_commands.Choice[str]] = []
    for key, card in cards.items():
        if not isinstance(card, dict):
            continue
        name = str(card.get("name") or key)
        title = str(card.get("title") or "").strip()
        rarity = str(card.get("rarity") or "").strip()
        searchable = f"{key} {name} {title} {rarity}".casefold()
        if token and token not in searchable:
            continue

        label_parts = [str(key)]
        if rarity:
            label_parts.append(f"[{rarity}]")
        if title:
            label_parts.append(f"- {title}")
        choices.append(app_commands.Choice(name=" ".join(label_parts)[:100], value=str(key)))
        if len(choices) >= 25:
            break
    return choices


def _build_catalog_card_embed(data: dict[str, Any], card: dict[str, Any]) -> discord.Embed:
    """Build a card embed matching the collection_view layout exactly."""
    card_name = str(card.get("name", "Unknown"))
    title     = str(card.get("title", "")).strip()
    bio       = str(card.get("description", "")).strip() or "—"
    rarity     = str(card.get("rarity", "Common"))
    raw_stats  = card.get("stats", {})
    image_url  = str(card.get("image_url", "")).strip()

    # Catalog cards have no stars — show base stats at 0 stars
    scaled = compute_scaled_stats(card, 0)
    power  = compute_power(scaled)

    mastery_list = normalize_mastery_list(card.get("mastery", card.get("masteries", [])))
    mastery_str  = "  ".join(f"• {m}" for m in mastery_list) if mastery_list else "—"

    unique_path,  unique_path_desc  = _resolve_field(card.get("unique_path"),  card.get("unique_path_description"))
    unique_skill, unique_skill_desc = _resolve_unique_skills(card)

    heading = f"{_rarity_icon(rarity)} {rarity} • {card_name}"
    if title:
        heading += f"\n{title}"

    body = (
        f"{heading}\n\n"
        f"{bio}\n\n"
        "**Combat Stats**\n"
        f"STR {int(scaled.get('strength', 0))} · SPD {int(scaled.get('speed', 0))} · "
        f"END {int(scaled.get('endurance', 0))} · TEC {int(scaled.get('technique', 0))} · "
        f"IQ {int(scaled.get('iq', 0))} · BIQ {int(scaled.get('battle_iq', 0))}\n\n"
        f"**Progression**\n"
        f"Stars: ☆☆☆☆☆ · Power: {power:,} · Base Stats\n\n"
        f"**Mastery**\n{mastery_str}\n\n"
        f"**Unique Path**\n{unique_path}\n{unique_path_desc}\n\n"
        f"**Unique Skill**\n{unique_skill}\n{unique_skill_desc}"
    )

    return make_embed(None, "LOOKISM HXCC • FIGHTER", body, color=0xE11D48, footer="Card Catalog", image_url=image_url)


class CardToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="card_info", description="View information about a catalog card.")
    async def card_info(self, interaction: discord.Interaction, card_name: str) -> None:
        data = self.bot.storage.load()
        catalog = data.get("cards", {})
        card = find_catalog_card(catalog, card_name)
        if card is None:
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Card Not Found", "No matching card exists in the catalog."),
                ephemeral=True,
            )
            return

        embed = _build_catalog_card_embed(data, card)
        await smart_reply(interaction, embed=embed)

    @card_info.autocomplete("card_name")
    async def card_info_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return _card_name_choices(self.bot.storage.load(), current)

    async def _set_flag(self, interaction: discord.Interaction, query: str, key: str, value: bool, title_key: str) -> None:
        from bot.utils.checks import ensure_registered
        from bot.utils.cards_logic import find_owned_instance
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)

        def mutate(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            inv = state["players"][user_id]["user"].setdefault("inventory", [])
            item, idx = find_owned_instance(inv, query)
            if item is None or idx is None:
                return state, False
            inv[idx][key] = value
            return state, True

        data, updated = self.bot.storage.with_lock(mutate)
        if not updated:
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Instance Not Found", "No matching owned card found."),
                ephemeral=True,
            )
            return

        await smart_reply(
            interaction,
            embed=make_embed(data, f"{e(title_key, data)} Updated", "Card instance flag updated."),
            ephemeral=True,
        )

    @app_commands.command(name="card_lock", description="Lock an owned card instance.")
    async def card_lock(self, interaction: discord.Interaction, query: str) -> None:
        await self._set_flag(interaction, query, "locked", True, "lock")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardToolsCog(bot))
