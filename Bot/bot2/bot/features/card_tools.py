"""Card lookup command for LOOKISM HXCC."""

from __future__ import annotations

from typing import Any

import discord
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
        "╭─ Bio\n"
        f"│ {bio}\n"
        "╰────────────────\n\n"
        "╭─ Combat Stats\n"
        f"│ 💪 STR: {int(scaled.get('strength', 0))}\n"
        f"│ ⚡ SPD: {int(scaled.get('speed', 0))}\n"
        f"│ 🛡 END: {int(scaled.get('endurance', 0))}\n"
        f"│ 🎯 TEC: {int(scaled.get('technique', 0))}\n"
        f"│ 🧠 IQ: {int(scaled.get('iq', 0))}\n"
        f"│ 🔮 BIQ: {int(scaled.get('battle_iq', 0))}\n"
        "╰────────────────\n\n"
        "╭─ Progression\n"
        f"│ ⭐ Stars: ☆☆☆☆☆\n"
        f"│ ⚡ Power: {power:,}\n"
        "│ 🔓 Status: Base Stats\n"
        "╰────────────────\n\n"
        "╭─ Mastery\n"
        f"│ {mastery_str}\n"
        "╰────────────────\n\n"
        "╭─ Unique Path\n"
        f"│ {unique_path}\n"
        f"│ {unique_path_desc}\n"
        "╰────────────────\n\n"
        "╭─ Unique Skill\n"
        f"│ {unique_skill}\n"
        f"│ {unique_skill_desc}\n"
        "╰────────────────"
    )

    return make_embed(None, "LOOKISM HXCC • FIGHTER", body, color=0xE11D48, footer="Card Catalog", image_url=image_url)


class CardToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="card_info")
    async def card_info(self, ctx: commands.Context, card_name: str) -> None:
        data = self.bot.storage.load()
        catalog = data.get("cards", {})
        card = find_catalog_card(catalog, card_name)
        if card is None:
            await smart_reply(
                ctx,
                embed=make_embed(data, f"{e('warning', data)} Card Not Found", "No matching card exists in the catalog."),
                ephemeral=True,
            )
            return

        embed = _build_catalog_card_embed(data, card)
        await smart_reply(ctx, embed=embed)

    async def _set_flag(self, ctx: commands.Context, query: str, key: str, value: bool, title_key: str) -> None:
        from bot.utils.checks import ensure_registered
        from bot.utils.cards_logic import find_owned_instance
        if not await ensure_registered(ctx, self.bot.storage):
            return

        user_id = str(ctx.author.id)

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
                ctx,
                embed=make_embed(data, f"{e('warning', data)} Instance Not Found", "No matching owned card found."),
                ephemeral=True,
            )
            return

        await smart_reply(
            ctx,
            embed=make_embed(data, f"{e(title_key, data)} Updated", "Card instance flag updated."),
            ephemeral=True,
        )

    @commands.command(name="card_lock")
    async def card_lock(self, ctx: commands.Context, query: str) -> None:
        await self._set_flag(ctx, query, "locked", True, "lock")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardToolsCog(bot))
