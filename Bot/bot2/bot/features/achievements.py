"""Achievements commands for players and owners."""

from __future__ import annotations

import math
from typing import Any

import discord
from discord.ext import commands

from bot.utils.achievement_logic import TIER_EMOJI_KEY, ensure_player_achievements, format_entries, grant, list_catalog, remove, reset
from bot.utils.checks import is_owner
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply



class AchievementsView(discord.ui.View):
    def __init__(
        self,
        data: dict[str, Any],
        target_id: str,
        target_name: str,
        earned_lines: list[str],
        locked_lines: list[str],
        invoker_id: str,
    ) -> None:
        super().__init__(timeout=120)
        self.data = data
        self.target_id = target_id
        self.target_name = target_name
        self.earned_lines = earned_lines
        self.locked_lines = locked_lines
        self.invoker_id = invoker_id
        self.mode = "earned"
        self.page = 0
        self.page_size = 8

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.invoker_id:
            await smart_reply(interaction, 
                embed=make_embed(self.data, f"{e('warning', self.data)} Not allowed", "Only the command invoker can use this menu."),
                ephemeral=True,
            )
            return False
        return True

    def _current_lines(self) -> list[str]:
        return self.earned_lines if self.mode == "earned" else self.locked_lines

    def _build_embed(self) -> discord.Embed:
        lines = self._current_lines()
        total_pages = max(1, math.ceil(max(1, len(lines)) / self.page_size))
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.page_size
        chunk = lines[start : start + self.page_size]

        mode_name = "Earned" if self.mode == "earned" else "Locked"
        display_lines = list(chunk) if chunk else ["Nothing to show."]
        description = box(f"Achievements — {mode_name}", display_lines)

        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= total_pages - 1

        return make_embed(
            self.data,
            f"{mode_name} • {self.target_name}",
            description,
            fields=[(f"{e('page', self.data)} Page", f"{self.page + 1}/{total_pages}", True)],
        )

    @discord.ui.select(
        placeholder="View",
        options=[
            discord.SelectOption(label="Earned", value="earned"),
            discord.SelectOption(label="Locked", value="locked"),
        ],
    )
    async def mode_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        self.mode = select.values[0]
        self.page = 0
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page -= 1
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


class AchievementsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _owner_embed(self, data: dict[str, Any]) -> discord.Embed:
        return make_embed(data, f"{e('no', data)} Owner Only", "You are not allowed to use this command.")

    @commands.command(name="achievements")
    async def achievements(self, ctx: commands.Context, user: discord.User | None = None) -> None:
        data = self.bot.storage.load()
        target = user or ctx.author
        target_id = str(target.id)

        players = data.get("players", {})
        if not isinstance(players, dict) or target_id not in players:
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('warning', data)} Profile Missing", "Target user is not registered."),
                ephemeral=True,
            )
            return

        player = players[target_id]
        if not isinstance(player, dict):
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('warning', data)} Profile Missing", "Target user data is invalid."),
                ephemeral=True,
            )
            return

        achievements = ensure_player_achievements(player)
        earned = achievements.get("earned", {})
        earned_dict = earned if isinstance(earned, dict) else {}

        catalog_rows = list_catalog(data)
        earned_lines = format_entries(data, earned_dict)

        locked_lines: list[str] = []
        for row in catalog_rows:
            achv_id = str(row.get("id", ""))
            if achv_id in earned_dict:
                continue
            icon = e(str(row.get("icon_key", "achievement")), data)
            tier = str(row.get("tier", "Bronze"))
            tier_icon = e(TIER_EMOJI_KEY.get(tier, "bronze"), data)
            locked_lines.append(f"{e('lock', data)} {icon} {row.get('name', achv_id)} — {row.get('desc', '')} • {tier_icon} {tier}")

        view = AchievementsView(
            data=data,
            target_id=target_id,
            target_name=target.display_name,
            earned_lines=earned_lines,
            locked_lines=locked_lines,
            invoker_id=str(ctx.author.id),
        )

        total_earned = len(earned_dict)
        total_catalog = len(catalog_rows)
        embed = view._build_embed()
        embed.insert_field_at(0, name=f"{e('earned', data)} Progress", value=f"{total_earned}/{total_catalog}", inline=True)

        await smart_reply(ctx, embed=embed, view=view, ephemeral=True)

    @commands.command(name="o_achievement_grant")
    async def o_achievement_grant(
        self,
        ctx: commands.Context,
        user: discord.User,
        achievement_id: str,
        note: str | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=self._owner_embed(data), ephemeral=True)
            return

        def mutate(state: dict[str, Any]) -> tuple[bool, str]:
            return grant(state, str(user.id), achievement_id, note or "")

        ok, message = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        catalog = data.get("achievement_catalog", {}) if isinstance(data.get("achievement_catalog"), dict) else {}
        row = catalog.get(achievement_id, {}) if isinstance(catalog, dict) else {}
        icon = e(str(row.get("icon_key", "achievement")), data) if isinstance(row, dict) else e("achievement", data)
        tier = str(row.get("tier", "Bronze")) if isinstance(row, dict) else "Bronze"
        tier_icon = e(TIER_EMOJI_KEY.get(tier, "bronze"), data)

        title = f"{e('grant', data)} Achievement Granted" if ok else f"{e('warning', data)} Grant Failed"
        desc = f"{icon} {achievement_id}\n{tier_icon} {tier}\n{message}"
        await smart_reply(ctx, embed=make_embed(data, title, desc), ephemeral=True)

    @commands.command(name="o_achievement_remove")
    async def o_achievement_remove(self, ctx: commands.Context, user: discord.User, achievement_id: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=self._owner_embed(data), ephemeral=True)
            return

        ok, message = self.bot.storage.with_lock(lambda state: remove(state, str(user.id), achievement_id))
        data = self.bot.storage.load()
        title = f"{e('remove', data)} Achievement Removed" if ok else f"{e('warning', data)} Remove Failed"
        await smart_reply(ctx, embed=make_embed(data, title, message), ephemeral=True)

    @commands.command(name="o_achievement_reset")
    async def o_achievement_reset(
        self,
        ctx: commands.Context,
        user: discord.User,
        mode: str | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=self._owner_embed(data), ephemeral=True)
            return

        reset_mode = mode if mode else "earned_only"
        ok, message = self.bot.storage.with_lock(lambda state: reset(state, str(user.id), reset_mode))
        data = self.bot.storage.load()
        title = f"{e('reset', data)} Achievement Reset" if ok else f"{e('warning', data)} Reset Failed"
        await smart_reply(ctx, embed=make_embed(data, title, message), ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AchievementsCog(bot))
