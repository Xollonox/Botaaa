"""Owner-only reward setting commands (o_ prefix only)."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from bot.config import OWNER_GUILD_ID

from bot.utils.checks import is_owner
from bot.utils.reward_logic import build_rates, format_rates_block, validate_rates
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class OwnerRewardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _set_reward(
        self,
        interaction: discord.Interaction,
        reward_type: str,
        amount: int,
        bonus_enabled: bool,
        rates_common: int,
        rates_rare: int,
        rates_epic: int,
        rates_legendary: int,
        rates_mythical: int,
        rates_infernal: int,
        rates_abyssal: int,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            embed = make_embed(data, f"{e('no', data)} Owner Only", "You are not allowed to use this command.")
            await smart_reply(interaction, embed=embed, ephemeral=True)
            return

        rates = build_rates(
            rates_common,
            rates_rare,
            rates_epic,
            rates_legendary,
            rates_mythical,
            rates_infernal,
            rates_abyssal,
        )

        if bonus_enabled:
            valid, message = validate_rates(rates)
            if not valid:
                error_embed = make_embed(
                    data,
                    f"{e('warning', data)} Invalid Bonus Rates",
                    message,
                    fields=[(f"{e('info', data)} Provided Rates", format_rates_block(rates), False)],
                )
                await smart_reply(interaction, embed=error_embed, ephemeral=True)
                return

        def mutate(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            config = state.setdefault("config", {})
            rewards_cfg = config.setdefault("rewards", {})
            card_bonus_cfg = config.setdefault("reward_card_bonus", {})
            reward_cfg = card_bonus_cfg.setdefault(reward_type, {"enabled": False, "rates": {"Common": 100}})

            old_amount = int(rewards_cfg.get(reward_type, 0))
            rewards_cfg[reward_type] = int(amount)
            reward_cfg["enabled"] = bool(bonus_enabled)
            reward_cfg["rates"] = dict(rates)
            return old_amount, state

        old_amount, updated_data = self.bot.storage.with_lock(mutate)
        bonus_state = f"Enabled {e('ok', updated_data)}" if bonus_enabled else f"Disabled {e('no', updated_data)}"

        embed = make_embed(
            updated_data,
            f"{e('settings', updated_data)} Reward Settings Updated",
            "Reward configuration has been saved.",
            fields=[
                ("Reward Type", reward_type.capitalize(), False),
                (f"{e('coin', updated_data)} Coin Amount", f"{old_amount} -> {amount}", False),
                (f"{e('card', updated_data)} Card Bonus", bonus_state, False),
                (f"{e('info', updated_data)} Rarity Rates", format_rates_block(rates), False),
            ],
        )
        await smart_reply(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="o_set_hourly", description="Owner: set hourly reward coins and card bonus rates.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_set_hourly(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, None],
        bonus_enabled: bool = False,
        rates_common: app_commands.Range[int, 0, None] = 100,
        rates_rare: app_commands.Range[int, 0, None] = 0,
        rates_epic: app_commands.Range[int, 0, None] = 0,
        rates_legendary: app_commands.Range[int, 0, None] = 0,
        rates_mythical: app_commands.Range[int, 0, None] = 0,
        rates_infernal: app_commands.Range[int, 0, None] = 0,
        rates_abyssal: app_commands.Range[int, 0, None] = 0,
    ) -> None:
        await self._set_reward(
            interaction,
            "hourly",
            amount,
            bonus_enabled,
            rates_common,
            rates_rare,
            rates_epic,
            rates_legendary,
            rates_mythical,
            rates_infernal,
            rates_abyssal,
        )

    @app_commands.command(name="o_set_daily", description="Owner: set daily reward coins and card bonus rates.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_set_daily(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, None],
        bonus_enabled: bool = False,
        rates_common: app_commands.Range[int, 0, None] = 100,
        rates_rare: app_commands.Range[int, 0, None] = 0,
        rates_epic: app_commands.Range[int, 0, None] = 0,
        rates_legendary: app_commands.Range[int, 0, None] = 0,
        rates_mythical: app_commands.Range[int, 0, None] = 0,
        rates_infernal: app_commands.Range[int, 0, None] = 0,
        rates_abyssal: app_commands.Range[int, 0, None] = 0,
    ) -> None:
        await self._set_reward(
            interaction,
            "daily",
            amount,
            bonus_enabled,
            rates_common,
            rates_rare,
            rates_epic,
            rates_legendary,
            rates_mythical,
            rates_infernal,
            rates_abyssal,
        )

    @app_commands.command(name="o_set_weekly", description="Owner: set weekly reward coins and card bonus rates.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_set_weekly(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, None],
        bonus_enabled: bool = False,
        rates_common: app_commands.Range[int, 0, None] = 100,
        rates_rare: app_commands.Range[int, 0, None] = 0,
        rates_epic: app_commands.Range[int, 0, None] = 0,
        rates_legendary: app_commands.Range[int, 0, None] = 0,
        rates_mythical: app_commands.Range[int, 0, None] = 0,
        rates_infernal: app_commands.Range[int, 0, None] = 0,
        rates_abyssal: app_commands.Range[int, 0, None] = 0,
    ) -> None:
        await self._set_reward(
            interaction,
            "weekly",
            amount,
            bonus_enabled,
            rates_common,
            rates_rare,
            rates_epic,
            rates_legendary,
            rates_mythical,
            rates_infernal,
            rates_abyssal,
        )

    @app_commands.command(name="o_set_monthly", description="Owner: set monthly reward coins and card bonus rates.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_set_monthly(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, None],
        bonus_enabled: bool = True,
        rates_common: app_commands.Range[int, 0, None] = 50,
        rates_rare: app_commands.Range[int, 0, None] = 30,
        rates_epic: app_commands.Range[int, 0, None] = 15,
        rates_legendary: app_commands.Range[int, 0, None] = 4,
        rates_mythical: app_commands.Range[int, 0, None] = 1,
        rates_infernal: app_commands.Range[int, 0, None] = 0,
        rates_abyssal: app_commands.Range[int, 0, None] = 0,
    ) -> None:
        await self._set_reward(
            interaction,
            "monthly",
            amount,
            bonus_enabled,
            rates_common,
            rates_rare,
            rates_epic,
            rates_legendary,
            rates_mythical,
            rates_infernal,
            rates_abyssal,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OwnerRewardsCog(bot))
