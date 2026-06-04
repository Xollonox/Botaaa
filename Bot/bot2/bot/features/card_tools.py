"""Card lookup command for LOOKISM HXCC."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import compute_power, compute_scaled_stats, find_catalog_card
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


def _build_catalog_card_embed(data: dict[str, Any], card: dict[str, Any]) -> discord.Embed:
    """Build a card embed matching the collection_view layout exactly."""
    card_name = str(card.get("name", "Unknown"))
    rarity     = str(card.get("rarity", "Common"))
    raw_stats  = card.get("stats", {})
    image_url  = str(card.get("image_url", "")).strip()

    # Catalog cards have no stars — show base stats at 0 stars
    scaled = compute_scaled_stats(card, 0)
    power  = compute_power(scaled)

    mastery_raw  = card.get("mastery", [])
    mastery_list = [str(m).strip().title() for m in mastery_raw if str(m).strip()] if isinstance(mastery_raw, list) else []
    mastery_str  = "  ".join(f"• {m}" for m in mastery_list) if mastery_list else "—"

    unique_path,  unique_path_desc  = _resolve_field(card.get("unique_path"),  card.get("unique_path_description"))
    unique_skill, unique_skill_desc = _resolve_field(card.get("unique_skill"), card.get("unique_skill_description"))

    body = (
        f"{_rarity_icon(rarity)} {rarity} • {card_name}\n\n"
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

    @app_commands.command(name="fuse", description="Fuse 3 copies of the same card → +1 star.")
    async def fuse(self, interaction: discord.Interaction, card_name: str) -> None:
        from bot.utils.checks import ensure_registered
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)
        target  = str(card_name).strip()

        def mutate(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            player = data.get("players", {}).get(user_id, {})
            user   = player.get("user", {}) if isinstance(player, dict) else {}
            inv    = user.get("inventory", []) if isinstance(user, dict) else []
            if not isinstance(inv, list):
                return "no_inventory", {}

            matches: list[tuple[int, dict[str, Any]]] = []
            for idx, item in enumerate(inv):
                if not isinstance(item, dict):
                    continue
                if str(item.get("card_name", "")).lower() != target.lower():
                    continue
                if item.get("locked") or item.get("squad_locked") or item.get("market_locked") or item.get("trade_locked"):
                    continue
                matches.append((idx, item))

            if len(matches) < 3:
                return "need_three", {"have": len(matches)}

            matches.sort(key=lambda p: int(p[1].get("stars", 0)), reverse=True)
            primary_idx, primary = matches[0]
            sacrifice_idxs = sorted([matches[1][0], matches[2][0]], reverse=True)

            cur_stars = int(primary.get("stars", 0))
            if cur_stars >= 5:
                return "max_stars", {"card_name": str(primary.get("card_name", target))}

            for i in sacrifice_idxs:
                if i == primary_idx:
                    continue
                inv.pop(i)
                if i < primary_idx:
                    primary_idx -= 1

            inv[primary_idx]["stars"] = min(5, cur_stars + 1)
            return "ok", {
                "card_name": str(inv[primary_idx].get("card_name", target)),
                "stars":     int(inv[primary_idx]["stars"]),
                "rarity":    str(inv[primary_idx].get("rarity", "")),
            }

        result, info = self.bot.storage.with_lock(mutate)

        if result == "ok":
            stars = int(info.get("stars", 0))
            body = (
                f"╭─ ✨ Fusion Complete\n"
                f"│ {info.get('card_name', target)}\n"
                f"│ Rarity: {info.get('rarity', '')}\n"
                f"│ Stars: {'★' * stars}{'☆' * (5 - stars)}\n"
                "│ 2 duplicates consumed.\n"
                "╰────────────────"
            )
            await smart_reply(interaction, embed=make_embed(None, "LOOKISM HXCC • FUSION", body, color=0x2ECC71))
            return

        if result == "need_three":
            have = int(info.get("have", 0))
            await error_reply(interaction, f"Need 3 unlocked copies of **{target}** to fuse (you have {have}).")
            return
        if result == "max_stars":
            await error_reply(interaction, f"**{info.get('card_name', target)}** is already at 5★.")
            return
        await error_reply(interaction, "Inventory unavailable.")

    @fuse.autocomplete("card_name")
    async def fuse_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        user_id = str(interaction.user.id)
        data = self.bot.storage.load()
        player = data.get("players", {}).get(user_id, {})
        inv = player.get("user", {}).get("inventory", []) if isinstance(player, dict) else []
        if not isinstance(inv, list):
            return []
        counts: dict[str, int] = {}
        rarities: dict[str, str] = {}
        for item in inv:
            if not isinstance(item, dict):
                continue
            if item.get("locked") or item.get("squad_locked") or item.get("market_locked") or item.get("trade_locked"):
                continue
            name = str(item.get("card_name", ""))
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            rarities.setdefault(name, str(item.get("rarity", "")))
        token = current.lower()
        out: list[app_commands.Choice[str]] = []
        for name, count in counts.items():
            if count < 3:
                continue
            if token and token not in name.lower():
                continue
            rarity = rarities.get(name, "")
            label = f"{_rarity_icon(rarity)} {name}  [{rarity}]  ×{count}"
            out.append(app_commands.Choice(name=label[:100], value=name))
            if len(out) >= 25:
                break
        return out


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardToolsCog(bot))
