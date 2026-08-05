"""Card lookup command for LOOKISM CG."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import (
    compute_power,
    compute_scaled_stats,
    find_catalog_card,
    resolve_mastery_list,
    resolve_unique_path,
    resolve_unique_skills,
    wrap_box_lines,
)
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply


def _rarity_icon(rarity: str) -> str:
    from bot.data.constants import rarity_icon
    return rarity_icon(str(rarity).title()) or "⚪"


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
    image_url  = str(card.get("image_url", "")).strip()

    # Catalog cards have no stars — show base stats at 0 stars
    scaled = compute_scaled_stats(card, 0)
    power  = compute_power(scaled)

    mastery_list = resolve_mastery_list(card)
    mastery_str  = "  ".join(f"• {m}" for m in mastery_list) if mastery_list else "—"

    skills = resolve_unique_skills(card)
    path_name, path_desc, path_active = resolve_unique_path(card)

    heading = f"{_rarity_icon(rarity)} {rarity} • {card_name}"
    if title:
        heading += f"\n{title}"

    bio_body = "\n".join(wrap_box_lines(bio))
    body = (
        f"{heading}\n\n"
        "╭─ Description\n"
        f"{bio_body}\n"
        "╰────────────────\n"
        "╭─ Combat Stats\n"
        f"│ 💪 STR: {int(scaled.get('strength', 0))}\n"
        f"│ ⚡ SPD: {int(scaled.get('speed', 0))}\n"
        f"│ 🛡 END: {int(scaled.get('endurance', 0))}\n"
        f"│ 🎯 TEC: {int(scaled.get('technique', 0))}\n"
        f"│ 🧠 IQ: {int(scaled.get('iq', 0))}\n"
        f"│ 🔮 BIQ: {int(scaled.get('battle_iq', 0))}\n"
        "╰────────────────\n"
        "╭─ Progression\n"
        f"│ ⭐ Stars: ☆☆☆☆☆\n"
        f"│ ⚡ Power: {power:,}\n"
        "│ 🔓 Status: Base Stats\n"
        "╰────────────────"
    )

    if mastery_list:
        body += (
            "\n╭─ Mastery\n"
            f"│ {mastery_str}\n"
            "╰────────────────"
        )

    if skills:
        skill_lines: list[str] = []
        for name, desc in skills:
            skill_lines.append(f"│ • {name}")
            if desc:
                skill_lines.extend(wrap_box_lines(desc, prefix="│   "))
        body += "\n╭─ Unique Skill\n" + "\n".join(skill_lines) + "\n╰────────────────"

    if path_name:
        path_kind = " [Active]" if path_active else " [Passive]"
        path_lines = [f"│ • {path_name}"]
        if path_desc:
            path_lines.extend(wrap_box_lines(path_desc, prefix="│   "))
        body += f"\n╭─ Unique Path{path_kind}\n" + "\n".join(path_lines) + "\n╰────────────────"

    return make_embed(None, "LOOKISM CG • FIGHTER", body, color=0xE11D48, footer="Card Catalog", image_url=image_url)


class CardToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="card_info", description="View information about a catalog card.")
    async def card_info(self, interaction: discord.Interaction, card_name: str) -> None:
        await interaction.response.defer()
        data = await self.bot.storage.load()
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
        return _card_name_choices(self.bot.storage.load_readonly(), current)

    async def _set_flag(self, interaction: discord.Interaction, query: str, key: str, value: bool, title_key: str) -> None:
        await interaction.response.defer(ephemeral=True)
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

        data, updated = await self.bot.storage.with_lock(mutate)
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
