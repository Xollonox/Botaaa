"""Economy commands for balances and owner balance adjustments."""

from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from bot.utils.checks import ensure_registered, is_owner, is_registered
from bot.utils.economy_logic import add_balance, add_premium, cooldown_remaining, fmt_duration
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply


BALANCE_COLOR = 0xE11D48
REWARD_COOLDOWNS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,
}


def _timer_text(user_data: dict[str, Any], key: str) -> str:
    cooldowns = user_data.get("cooldowns", {})
    if not isinstance(cooldowns, dict):
        return "Ready"
    last = int(cooldowns.get(key, 0) or 0)
    remaining = cooldown_remaining(last, REWARD_COOLDOWNS[key], now_ts())
    return "Ready" if remaining <= 0 else fmt_duration(remaining)


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="balance")
    async def balance(self, ctx: commands.Context) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return

        data = self.bot.storage.load()
        user_data = data.get("players", {}).get(str(ctx.author.id), {}).get("user", {})

        coins = int(user_data.get("balance", 0))
        gems = int(user_data.get("premium_balance", 0))
        trophies = int(user_data.get("trophies", 0))
        league = str(user_data.get("rank", "Copper"))

        embed = make_embed(
            None,
            "LOOKISM HXCC • WALLET",
            (
                f"**WALLET — {ctx.author.display_name}**\n\n"
                "╭─ Currency\n"
                f"│ Coins: {coins:,}\n"
                f"│ Gems: {gems:,}\n"
                "╰────────────────"
            ),
            color=BALANCE_COLOR,
            footer="Economy",
        )
        await smart_reply(ctx, embed=embed, ephemeral=True)

    # ─── Owner Commands ──────────────────────────────────────────────────────

    @commands.command(name="o_add_balance")
    async def o_add_balance(
        self,
        ctx: commands.Context,
        target: discord.User,
        amount: int,
    ) -> None:
        if not is_owner(ctx):
            data = self.bot.storage.load()
            embed = make_embed(
                data,
                f"{e('no', data)} Access Denied",
                "This command is restricted to bot owners only.",
            )
            await smart_reply(ctx, embed=embed, ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, int, int]:
            if not is_registered(data, target_id):
                return False, 0, 0
            user = data.get("players", {}).get(target_id, {}).get("user", {})
            before = int(user.get("balance", 0))
            after = add_balance(user, amount)
            return True, before, after

        ok, before, after = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            embed = make_embed(
                data,
                f"{e('warning', data)} User Not Registered",
                f"{target.mention} must run `!start` before receiving balance adjustments.",
            )
            await smart_reply(ctx, embed=embed, ephemeral=True)
            return

        embed = make_embed(
            data,
            f"{e('ok', data)} Balance Updated",
            f"{e('coin', data)} Coins have been added successfully.",
            fields=[
                ("Recipient", f"{target.mention}\n`{target.id}`", True),
                (f"{e('coin', data)} Amount Added", f"**+{amount:,}**", True),
                (f"{e('coin', data)} Before → After", f"{before:,} → **{after:,}**", True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)

    @commands.command(name="o_remove_balance")
    async def o_remove_balance(
        self,
        ctx: commands.Context,
        target: discord.User,
        amount: int,
    ) -> None:
        if not is_owner(ctx):
            data = self.bot.storage.load()
            embed = make_embed(
                data,
                f"{e('no', data)} Access Denied",
                "This command is restricted to bot owners only.",
            )
            await smart_reply(ctx, embed=embed, ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, int, int]:
            if not is_registered(data, target_id):
                return False, 0, 0
            user = data.get("players", {}).get(target_id, {}).get("user", {})
            before = int(user.get("balance", 0))
            after = max(0, before - amount)
            user["balance"] = after
            return True, before, after

        ok, before, after = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            embed = make_embed(
                data,
                f"{e('warning', data)} User Not Registered",
                f"{target.mention} must run `!start` before balance adjustments.",
            )
            await smart_reply(ctx, embed=embed, ephemeral=True)
            return

        embed = make_embed(
            data,
            f"{e('ok', data)} Balance Updated",
            f"{e('coin', data)} Coins have been removed successfully.",
            fields=[
                ("Recipient", f"{target.mention}\n`{target.id}`", True),
                (f"{e('coin', data)} Amount Removed", f"**-{amount:,}**", True),
                (f"{e('coin', data)} Before → After", f"{before:,} → **{after:,}**", True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)

    @commands.command(name="o_add_premium")
    async def o_add_premium(
        self,
        ctx: commands.Context,
        target: discord.User,
        amount: int,
    ) -> None:
        if not is_owner(ctx):
            data = self.bot.storage.load()
            embed = make_embed(
                data,
                f"{e('no', data)} Access Denied",
                "This command is restricted to bot owners only.",
            )
            await smart_reply(ctx, embed=embed, ephemeral=True)
            return

        target_id = str(target.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, int, int]:
            if not is_registered(data, target_id):
                return False, 0, 0
            user = data.get("players", {}).get(target_id, {}).get("user", {})
            before = int(user.get("premium_balance", 0))
            after = add_premium(user, amount)
            return True, before, after

        ok, before, after = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            embed = make_embed(
                data,
                f"{e('warning', data)} User Not Registered",
                f"{target.mention} must run `!start` before receiving premium adjustments.",
            )
            await smart_reply(ctx, embed=embed, ephemeral=True)
            return

        embed = make_embed(
            data,
            f"{e('ok', data)} Premium Updated",
            f"{e('gem', data)} Premium gems have been added successfully.",
            fields=[
                ("Recipient", f"{target.mention}\n`{target.id}`", True),
                (f"{e('gem', data)} Amount Added", f"**+{amount:,}**", True),
                (f"{e('gem', data)} Before → After", f"{before:,} → **{after:,}**", True),
            ],
        )
        embed.set_footer(text="Admin Control")
        await smart_reply(ctx, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
