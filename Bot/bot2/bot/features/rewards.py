"""Reward claim commands with cooldowns and economy reward UI."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import build_card_instance
from bot.utils.checks import ensure_registered
from bot.utils.economy_logic import cooldown_remaining, fmt_duration
from bot.utils.interaction_visibility import error_reply
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed
from bot.features.tutorial import advance_tutorial

REWARD_COOLDOWNS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,
}

HOURLY_COLOR  = 0x5C6BC0  # indigo/grey
DAILY_COLOR   = 0x1565C0  # blue
WEEKLY_COLOR  = 0x6A1B9A  # purple
MONTHLY_COLOR = 0xF9A825  # gold

REWARD_CARD_RARITY = {
    "daily": "Common",
    "weekly": "Rare",
    "monthly": "Legendary",
}

# Phase-1 buff (revised): each reward is EITHER a card OR coins, never both.
# Coinflip per claim. Rarity pools are conservative — coins exist as a sink, not a printer.
REWARD_RATES: dict[str, dict[str, int]] = {
    "daily":   {"Common": 100},
    "weekly":  {"Common": 70, "Rare": 30},
    "monthly": {"Rare": 60, "Epic": 35, "Legendary": 5},
}

REWARD_COIN_BONUS: dict[str, int] = {
    "daily":   150,
    "weekly":  1_500,
    "monthly": 10_000,
}

# Probability of getting the coin-only path instead of the card-only path.
REWARD_COIN_CHANCE: dict[str, float] = {
    "daily":   0.5,
    "weekly":  0.5,
    "monthly": 0.5,
}


def _weighted_rarity(rates: dict[str, int]) -> str:
    pool: list[str] = []
    for rarity, weight in rates.items():
        try:
            w = int(weight)
        except (TypeError, ValueError):
            w = 0
        if w > 0:
            pool.extend([str(rarity)] * w)
    return random.choice(pool) if pool else ""


def _streak_multiplier(streak: int) -> float:
    """Calculate coin multiplier based on login streak."""
    if streak >= 30:
        return 3.0
    if streak >= 14:
        return 2.0
    if streak >= 7:
        return 1.5
    if streak >= 3:
        return 1.25
    return 1.0


def _reward_embed(*, panel: str, footer: str, body: str, color: int) -> discord.Embed:
    return make_embed(None, f"LOOKISM HXCC • {panel.upper()}", body, color=color, footer=footer)


def _pick_card_by_rarity(data: dict[str, Any], rarity: str) -> dict[str, Any] | None:
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        return None
    pool = [card for card in cards.values() if isinstance(card, dict) and str(card.get("rarity", "")) == rarity]
    if not pool:
        return None
    return random.choice(pool)


class RewardCardActionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, claimer_id: str, card_uid: str) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.claimer_id = str(claimer_id)
        self.card_uid = str(card_uid)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.claimer_id:
            await interaction.response.send_message("This reward belongs to another player.", ephemeral=True)
            return False
        return True

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="💰 Quick Sell", style=discord.ButtonStyle.secondary, row=0)
    async def quick_sell_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        uid = self.claimer_id
        card_uid = self.card_uid
        if not card_uid:
            await error_reply(interaction, "Card not found.")
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, int]:
            players = data.get("players", {})
            player = players.get(uid, {}) if isinstance(players, dict) else {}
            user = player.get("user", {}) if isinstance(player, dict) else {}
            inv = user.get("inventory", []) if isinstance(user, dict) else []
            if not isinstance(inv, list):
                return False, 0

            idx = next((i for i, row in enumerate(inv) if isinstance(row, dict) and str(row.get("uid", "")) == card_uid), -1)
            if idx < 0:
                return False, 0

            card = inv.pop(idx)
            rarity = str(card.get("rarity", "Common"))
            from bot.utils.market_logic import quick_sell_value
            sold_for = quick_sell_value(data, rarity)
            if sold_for <= 0:
                fallback = {"Common": 100, "Rare": 300, "Epic": 800,
                            "Legendary": 2000, "Mythical": 5000, "Infernal": 8000, "Abyssal": 12000}
                sold_for = fallback.get(rarity, 100)
            user["balance"] = int(user.get("balance", 0)) + sold_for
            return True, sold_for

        ok, sold_for = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message("Card no longer available.", ephemeral=True)
            return

        self._disable_all()
        embed = _reward_embed(
            panel="Rewards",
            footer="Rewards",
            body=(
                "**CARD SOLD**\n\n"
                "╭─ Sale\n"
                f"│ Coins Earned: +{sold_for:,}\n"
                "╰────────────────"
            ),
            color=HOURLY_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="➕ Add to Squad", style=discord.ButtonStyle.primary, row=0)
    async def add_to_squad_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await self._do_add_to_squad(interaction)
        except discord.errors.NotFound:
            pass  # interaction timed out — card is still in inventory

    async def _do_add_to_squad(self, interaction: discord.Interaction) -> None:
        uid = self.claimer_id
        card_uid = self.card_uid
        if not card_uid:
            await error_reply(interaction, "Card not found.")
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            from bot.utils.squad_logic import get_squad
            players = data.get("players", {})
            player = players.get(uid, {}) if isinstance(players, dict) else {}
            if not isinstance(player, dict):
                return False, "invalid"
            user = player.get("user", {}) if isinstance(player, dict) else {}
            inv = user.get("inventory", []) if isinstance(user, dict) else []
            if not isinstance(inv, list):
                return False, "invalid"

            squad = get_squad(player)
            active = squad.get("active", [])
            backup = squad.get("backup", [])
            all_slots = [str(u) for u in active + backup if str(u)]

            if len(all_slots) >= 4:
                return False, "full"

            card = next((row for row in inv if isinstance(row, dict) and str(row.get("uid", "")) == card_uid), None)
            if not isinstance(card, dict):
                return False, "missing"

            if card_uid in all_slots:
                return False, "exists"

            # Add to active if space, else backup
            if len(active) < 2:
                active.append(card_uid)
                squad["active"] = active
            else:
                backup.append(card_uid)
                squad["backup"] = backup
            card["squad_locked"] = True
            return True, "ok"

        ok, status = self.bot.storage.with_lock(mutate)
        if not ok:
            msg = "Squad is full (4 slots max)." if status == "full" else ("Card already in squad." if status == "exists" else "Unable to add card to squad.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        self._disable_all()
        embed = _reward_embed(
            panel="Rewards",
            footer="Rewards",
            body=(
                "**SQUAD UPDATED**\n\n"
                "╭─ Status\n"
                "│ Card added to squad\n"
                "│ Use /squad to manage your formation\n"
                "╰────────────────"
            ),
            color=DAILY_COLOR,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.errors.NotFound:
            pass


class RewardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _handle_hourly(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        now = now_ts()

        def mutate(data: dict[str, Any]) -> tuple[bool, int, int]:
            player = data["players"][user_id]
            user = player["user"]
            cooldowns = user.setdefault("cooldowns", {})
            last = int(cooldowns.get("hourly", 0))
            remaining = cooldown_remaining(last, REWARD_COOLDOWNS["hourly"], now)
            if remaining > 0:
                return False, remaining, int(user.get("balance", 0))

            user["balance"] = int(user.get("balance", 0)) + 100
            cooldowns["hourly"] = now
            return True, 0, int(user.get("balance", 0))

        claimed, remaining, new_balance = self.bot.storage.with_lock(mutate)

        if not claimed:
            embed = _reward_embed(
                panel="Hourly Reward",
                footer="Rewards",
                body=(
                    "**HOURLY REWARD**\n\n"
                    "╭─ Cooldown\n"
                    f"│ Remaining: {fmt_duration(remaining)}\n"
                    "╰────────────────"
                ),
                color=HOURLY_COLOR,
            )
            await interaction.followup.send(embed=embed)
            return

        embed = _reward_embed(
            panel="Hourly Reward",
            footer="Rewards",
            body=(
                "**HOURLY REWARD**\n\n"
                "╭─ Reward\n"
                "│ Coins Earned: +100\n"
                f"│ New Balance: {new_balance:,}\n"
                "╰────────────────\n\n"
                "Next Hourly: 1h"
            ),
            color=HOURLY_COLOR,
        )
        await interaction.followup.send(embed=embed)

    async def _handle_card_reward(self, interaction: discord.Interaction, reward_type: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        # Defer immediately — with_lock can be slow and Discord expects <3s
        await interaction.response.defer()

        rates       = REWARD_RATES.get(reward_type, {REWARD_CARD_RARITY[reward_type]: 1})
        coin_amount = int(REWARD_COIN_BONUS.get(reward_type, 0))
        coin_chance = float(REWARD_COIN_CHANCE.get(reward_type, 0.5))
        now = now_ts()
        user_id = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, int, dict[str, Any] | None, dict[str, Any] | None, str, int, bool, int, int, float]:
            player = data["players"][user_id]
            user = player["user"]
            cooldowns = user.setdefault("cooldowns", {})
            last = int(cooldowns.get(reward_type, 0))
            remaining = cooldown_remaining(last, REWARD_COOLDOWNS[reward_type], now)
            if remaining > 0:
                return False, remaining, None, None, "", 0, False, 0, 0, 1.0

            # Handle daily login streak
            streak = 0
            multiplier = 1.0
            effective_coin_amount = coin_amount
            if reward_type == "daily":
                today = datetime.utcnow().strftime("%Y-%m-%d")
                yesterday = datetime.utcfromtimestamp(now - 86400).strftime("%Y-%m-%d")

                current_streak = int(user.get("login_streak", 0))
                last_daily_date = user.get("last_daily_date", "")

                # Update streak logic
                if last_daily_date == yesterday:
                    # Continued streak
                    streak = current_streak + 1
                elif last_daily_date != today:
                    # Broken streak or first daily
                    streak = 1
                else:
                    # Already claimed today
                    streak = current_streak

                user["login_streak"] = streak
                user["last_daily_date"] = today
                multiplier = _streak_multiplier(streak)
                effective_coin_amount = int(coin_amount * multiplier)

            # Coinflip: either coins-only or card-only, never both.
            coins_path = random.random() < coin_chance
            new_balance = int(user.get("balance", 0))

            if coins_path:
                new_balance += effective_coin_amount
                user["balance"] = new_balance
                cooldowns[reward_type] = now
                if reward_type == "daily":
                    advance_tutorial(user, "claim_daily")
                return True, 0, None, None, "", new_balance, True, effective_coin_amount, streak, multiplier

            rarity = _weighted_rarity(rates)
            card_def = _pick_card_by_rarity(data, rarity) if rarity else None
            if not isinstance(card_def, dict):
                # Card pool empty — fall back to coin path so the claim still resolves.
                new_balance += effective_coin_amount
                user["balance"] = new_balance
                cooldowns[reward_type] = now
                if reward_type == "daily":
                    advance_tutorial(user, "claim_daily")
                return True, 0, None, None, "", new_balance, True, effective_coin_amount, streak, multiplier

            card_instance = build_card_instance(card_def, acquired_at=now, stars=0)
            inventory = user.setdefault("inventory", [])
            if not isinstance(inventory, list):
                inventory = []
                user["inventory"] = inventory
            inventory.append(card_instance)
            cooldowns[reward_type] = now
            if reward_type == "daily":
                advance_tutorial(user, "claim_daily")
            return True, 0, card_def, card_instance, rarity, new_balance, False, 0, streak, multiplier

        (
            claimed, remaining, card_def, card_instance,
            pulled_rarity, new_balance, coins_path, granted_coins, streak, multiplier,
        ) = self.bot.storage.with_lock(mutate)

        panel_map = {
            "daily": ("Daily Reward", "Daily Reward", DAILY_COLOR, "CARD OBTAINED"),
            "weekly": ("Weekly Reward", "Weekly Reward", WEEKLY_COLOR, "✨ Rare Card Obtained"),
            "monthly": ("Monthly Reward", "Monthly Reward", MONTHLY_COLOR, "🔥 Legendary Card Obtained"),
        }
        panel, footer, color, heading = panel_map[reward_type]

        if not claimed:
            embed = _reward_embed(
                panel=panel,
                footer=footer,
                body=(
                    f"**{heading}**\n\n"
                    "╭─ Cooldown\n"
                    f"│ Remaining: {fmt_duration(remaining)}\n"
                    "╰────────────────"
                ),
                color=color,
            )
            await interaction.followup.send(embed=embed)
            return

        if coins_path:
            # Build streak info for daily rewards
            streak_info = ""
            if reward_type == "daily" and streak > 0:
                streak_info = f"\n│ 🔥 Login Streak: {streak} days"
                if multiplier > 1.0:
                    bonus_pct = int((multiplier - 1.0) * 100)
                    streak_info += f"\n│ ✨ Streak Bonus: +{bonus_pct}%"
                # Check for milestones
                if streak in [3, 7, 14, 30]:
                    streak_info += f"\n│ 🎉 Milestone Reached: {streak} days!"

            embed = _reward_embed(
                panel=panel,
                footer=footer,
                body=(
                    f"**{heading.replace('CARD OBTAINED', 'COINS OBTAINED').replace('Card Obtained', 'Coins Obtained')}**\n\n"
                    "╭─ Reward\n"
                    f"│ Coins: +{granted_coins:,}\n"
                    f"│ New Balance: {new_balance:,}"
                    f"{streak_info}\n"
                    "╰────────────────"
                ),
                color=color,
            )
            await interaction.followup.send(embed=embed)
            return

        card_name = str((card_def or {}).get("name", "Unknown Card"))
        image_url = str((card_def or {}).get("image_url", "")).strip()
        if not image_url:
            image_url = "https://placehold.co/512x512/png?text=LOOKISM+CARD"

        # Build streak info for daily rewards
        streak_info = ""
        if reward_type == "daily" and streak > 0:
            streak_info = f"\n│ 🔥 Login Streak: {streak} days"
            if multiplier > 1.0:
                bonus_pct = int((multiplier - 1.0) * 100)
                streak_info += f"\n│ ✨ Streak Bonus: +{bonus_pct}%"
            # Check for milestones
            if streak in [3, 7, 14, 30]:
                streak_info += f"\n│ 🎉 Milestone Reached: {streak} days!"

        embed = _reward_embed(
            panel=panel,
            footer=footer,
            body=(
                f"**{heading}**\n\n"
                "╭─ Card\n"
                f"│ {card_name}\n"
                f"│ Rarity: {pulled_rarity}\n"
                "│ Stars: ☆☆☆☆☆"
                f"{streak_info}\n"
                "╰────────────────"
            ),
            color=color,
        )
        embed.set_image(url=image_url)

        view = RewardCardActionView(self.bot, user_id, str((card_instance or {}).get("uid", "")))
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="hourly", description="Claim your hourly reward.")
    async def hourly(self, interaction: discord.Interaction) -> None:
        await self._handle_hourly(interaction)

    @app_commands.command(name="daily", description="Claim your daily reward.")
    async def daily(self, interaction: discord.Interaction) -> None:
        await self._handle_card_reward(interaction, "daily")

    @app_commands.command(name="weekly", description="Claim your weekly reward.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        await self._handle_card_reward(interaction, "weekly")

    @app_commands.command(name="monthly", description="Claim your monthly reward.")
    async def monthly(self, interaction: discord.Interaction) -> None:
        await self._handle_card_reward(interaction, "monthly")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RewardsCog(bot))
