"""Owner profile configuration commands."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from bot.config import OWNER_GUILD_ID

from bot.utils.checks import is_owner
from bot.utils.profile_logic import build_profile_embed
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class ProfileOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _owner_only_embed(self, data: dict[str, Any]) -> discord.Embed:
        return make_embed(data, f"{e('no', data)} Owner Only", "You are not allowed to use this command.")

    def _card_choices(self, data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
        cards = data.get("cards", {})
        out: list[app_commands.Choice[str]] = []
        cur = current.lower().strip()
        if isinstance(cards, dict):
            for _, card in cards.items():
                if not isinstance(card, dict):
                    continue
                name = str(card.get("name", "")).strip()
                if not name:
                    continue
                if cur and cur not in name.lower():
                    continue
                out.append(app_commands.Choice(name=name[:100], value=name))
                if len(out) >= 25:
                    break
        return out

    @app_commands.command(name="o_profile_set_default_bg", description="Owner: set global default profile background URL.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_set_default_bg(self, interaction: discord.Interaction, image_url: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=self._owner_only_embed(data), ephemeral=True)
            return

        if image_url and not (image_url.startswith("http://") or image_url.startswith("https://")):
            await smart_reply(interaction, 
                embed=make_embed(data, f"{e('warning', data)} Invalid URL", f"{e('link', data)} URL must start with http:// or https://"),
                ephemeral=True,
            )
            return

        def mutate(data: dict[str, Any]) -> None:
            config = data.setdefault("config", {})
            profile_cfg = config.setdefault("profile", {}) if isinstance(config, dict) else {}
            if isinstance(profile_cfg, dict):
                profile_cfg["default_background_url"] = str(image_url)

        self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Default Background Updated", image_url or "(cleared)"), ephemeral=True)

    @app_commands.command(name="o_profile_set_default_featured", description="Owner: set default featured card by catalog name.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_set_default_featured(self, interaction: discord.Interaction, card_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=self._owner_only_embed(data), ephemeral=True)
            return

        cards = data.get("cards", {})
        if not isinstance(cards, dict) or card_name not in cards:
            await smart_reply(interaction, 
                embed=make_embed(data, f"{e('warning', data)} Card Not Found", "Select a valid catalog card."),
                ephemeral=True,
            )
            return

        def mutate(data: dict[str, Any]) -> None:
            config = data.setdefault("config", {})
            profile_cfg = config.setdefault("profile", {}) if isinstance(config, dict) else {}
            if isinstance(profile_cfg, dict):
                profile_cfg["default_featured_card_name"] = str(card_name)

        self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Default Featured Updated", card_name), ephemeral=True)

    @o_profile_set_default_featured.autocomplete("card_name")
    async def o_profile_set_default_featured_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        return self._card_choices(data, current)

    @app_commands.command(name="o_profile_set_premium", description="Owner: set premium status for a user.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_set_premium(self, interaction: discord.Interaction, user: discord.User, enabled: bool) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=self._owner_only_embed(data), ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> bool:
            player = data.get("players", {}).get(str(user.id), {})
            if not isinstance(player, dict):
                return False
            user_row = player.get("user", {})
            if not isinstance(user_row, dict):
                return False
            user_row["is_premium"] = bool(enabled)
            return True

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} User Not Registered", "Target user is not registered."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Premium Updated", f"{user.mention}: {enabled}"), ephemeral=True)

    @app_commands.command(name="o_profile_theme", description="Owner: set profile theme cosmetic.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_theme(self, interaction: discord.Interaction, user: discord.User, theme_name: str) -> None:
        await self._set_cosmetic(interaction, user, "theme", theme_name)

    @app_commands.command(name="o_profile_border", description="Owner: set profile border cosmetic.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_border(self, interaction: discord.Interaction, user: discord.User, border_id: str) -> None:
        await self._set_cosmetic(interaction, user, "border_id", border_id)

    @app_commands.command(name="o_profile_badge", description="Owner: set profile badge cosmetic.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_badge(self, interaction: discord.Interaction, user: discord.User, badge_id: str) -> None:
        await self._set_cosmetic(interaction, user, "badge_id", badge_id)

    async def _set_cosmetic(self, interaction: discord.Interaction, user: discord.User, key: str, value: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=self._owner_only_embed(data), ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> bool:
            player = data.get("players", {}).get(str(user.id), {})
            if not isinstance(player, dict):
                return False
            user_row = player.get("user", {})
            if not isinstance(user_row, dict):
                return False
            profile = user_row.setdefault("profile", {})
            cosmetics = profile.setdefault("cosmetics", {}) if isinstance(profile, dict) else {}
            if isinstance(cosmetics, dict):
                cosmetics[key] = str(value)
                return True
            return False

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} User Not Registered", "Target user is not registered."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Cosmetic Updated", f"{user.mention}: {key}={value}"), ephemeral=True)

    @app_commands.command(name="o_profile_preview", description="Owner: preview profile as owner view.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_profile_preview(self, interaction: discord.Interaction, user: discord.User) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=self._owner_only_embed(data), ephemeral=True)
            return
        if str(user.id) not in data.get("players", {}):
            await smart_reply(interaction, 
                embed=make_embed(data, f"{e('warning', data)} User Not Registered", "Target user is not registered."),
                ephemeral=True,
            )
            return

        embed = build_profile_embed(data, viewer_id=str(interaction.user.id), target_user_obj=user, viewer_is_owner=True)
        await smart_reply(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileOwnerCog(bot))
