"""Profile cog — slash commands & UI views. Rendering logic in profile_render.py."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.features.profile_render import (
    _MAX_BIO_LENGTH,
    _RARITY_ORDER,
    _resolve_card_by_uid,
    _sanitize_bio,
    build_featured_card_embed,
    build_profile_embed,
    render_profile_card,
)
from bot.utils.checks import ensure_registered
from bot.utils.ui import make_embed, simple_embed

logger = logging.getLogger(__name__)


class FeaturedCardSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, user_id: str, data: dict[str, Any], cards: list[dict[str, Any]]) -> None:
        self.bot = bot
        self.user_id = user_id
        self.data = data
        options: list[discord.SelectOption] = []
        for card in cards[:25]:
            card_name = str(card.get("card_name", "Unknown"))
            rarity    = str(card.get("rarity", "Common"))
            stars     = max(0, int(card.get("stars", 0)))
            uid       = str(card.get("uid", ""))
            stars_text = f" {'⭐' * stars}" if stars > 0 else ""
            options.append(discord.SelectOption(
                label=f"{card_name}{stars_text}"[:100],
                description=f"{rarity} • UID {uid[:8]}"[:100],
                value=uid,
            ))
        super().__init__(placeholder="Choose your featured card…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Only the command invoker can use this menu.", ephemeral=True)
            return
        selected_uid = self.values[0]

        def mutate(data: dict[str, Any]) -> tuple[str, str]:
            players = data.get("players", {})
            player  = players.get(self.user_id, {}) if isinstance(players, dict) else {}
            ud      = player.get("user", {}) if isinstance(player, dict) else {}
            profile = ud.setdefault("profile", {}) if isinstance(ud, dict) else {}
            if isinstance(profile, dict):
                profile["showcase_uid"] = selected_uid
            inv  = ud.get("inventory", []) if isinstance(ud, dict) else []
            card = _resolve_card_by_uid(inv if isinstance(inv, list) else [], selected_uid)
            if isinstance(card, dict):
                return str(card.get("card_name", "Unknown")), str(card.get("rarity", "Common"))
            return "Unknown", "Common"

        card_name, rarity = self.bot.storage.with_lock(mutate)
        embed = make_embed(None, "Featured Card Updated", f"🖼️ {card_name}\n{rarity}", footer="Player Profile")
        await interaction.response.send_message(embed=embed)


class FeaturedCardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: str, data: dict[str, Any], cards: list[dict[str, Any]]) -> None:
        super().__init__(timeout=120)
        self.add_item(FeaturedCardSelect(bot, user_id, data, cards))


class SetBioModal(discord.ui.Modal, title="Set Bio"):
    bio_text = discord.ui.TextInput(label="Bio text", style=discord.TextStyle.paragraph, max_length=_MAX_BIO_LENGTH)

    def __init__(self, cog: "ProfileCog") -> None:
        super().__init__(timeout=180)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.setbio(interaction, str(self.bio_text.value))


class ProfileActionView(discord.ui.View):
    def __init__(self, cog: "ProfileCog", invoker_id: int, target_user: discord.User | None = None) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.invoker_id = int(invoker_id)
        self.target_user = target_user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This profile panel belongs to another player.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✏ Set Bio", style=discord.ButtonStyle.secondary, row=0)
    async def set_bio(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(SetBioModal(self.cog))

    @discord.ui.button(label="⭐ Set Featured", style=discord.ButtonStyle.secondary, row=0)
    async def set_featured(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.setfeatured(interaction)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary, row=0)
    async def refresh_profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self.cog.profile(interaction, self.target_user)


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="View a premium profile card.")
    async def profile(self, interaction: discord.Interaction, user: discord.User | None = None) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        await interaction.response.defer()
        data      = self.bot.storage.load()
        target    = user or interaction.user
        target_id = str(target.id)
        players   = data.get("players", {})
        if not isinstance(players, dict) or target_id not in players:
            await interaction.followup.send("That user is not registered.", ephemeral=True)
            return
        view = ProfileActionView(self, interaction.user.id, target) if target.id == interaction.user.id else None
        try:
            file = await render_profile_card(data, target)
            embed = simple_embed("", footer="Player Profile")
            embed.set_image(url="attachment://profile_card.png")
            featured_embed = build_featured_card_embed(data, target)
            embeds = [embed, featured_embed]
            if view:
                await interaction.followup.send(embeds=embeds, files=[file], view=view)
            else:
                await interaction.followup.send(embeds=embeds, files=[file])
        except Exception:
            logger.exception("[PROFILE] Failed to render profile card for user=%s", target_id)
            embed = build_profile_embed(data, target)
            featured_embed = build_featured_card_embed(data, target)
            embeds = [embed, featured_embed]
            if view:
                await interaction.followup.send(embeds=embeds, view=view)
            else:
                await interaction.followup.send(embeds=embeds)

    async def setbio(self, interaction: discord.Interaction, text: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        cleaned = _sanitize_bio(text)
        if not cleaned:
            await interaction.response.send_message("Bio cannot be empty after cleaning.", ephemeral=True)
            return
        if len(cleaned) > _MAX_BIO_LENGTH:
            await interaction.response.send_message(f"Bio must be {_MAX_BIO_LENGTH} chars or fewer.", ephemeral=True)
            return
        uid = str(interaction.user.id)

        def mutate(payload: dict[str, Any]) -> None:
            players = payload.get("players", {})
            player  = players.get(uid, {}) if isinstance(players, dict) else {}
            ud      = player.get("user", {}) if isinstance(player, dict) else {}
            if not isinstance(ud, dict):
                return
            profile = ud.setdefault("profile", {})
            if isinstance(profile, dict):
                profile["bio"] = cleaned

        self.bot.storage.with_lock(mutate)
        embed = make_embed(None, "Bio Updated", f"*{cleaned}*", footer="Player Profile")
        await interaction.response.send_message(embed=embed)

    async def setfeatured(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data      = self.bot.storage.load()
        uid       = str(interaction.user.id)
        players   = data.get("players", {})
        player    = players.get(uid, {}) if isinstance(players, dict) else {}
        user_data = player.get("user", {}) if isinstance(player, dict) else {}
        inventory = user_data.get("inventory", []) if isinstance(user_data, dict) else []
        cards     = [i for i in inventory if isinstance(i, dict)] if isinstance(inventory, list) else []
        if not cards:
            await interaction.response.send_message("You need at least one card to set a featured card.", ephemeral=True)
            return
        cards_sorted = sorted(
            cards,
            key=lambda c: (_RARITY_ORDER.get(str(c.get("rarity", "Common")).lower(), 0), int(c.get("stars", 0))),
            reverse=True,
        )[:25]
        view  = FeaturedCardView(self.bot, uid, data, cards_sorted)
        embed = make_embed(None, "Set Featured Card", "Choose the card to showcase on your profile.", footer="Player Profile")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
