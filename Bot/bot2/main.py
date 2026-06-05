"""Entry point for Lookism Bot v2."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

# ---------------------------------------------------------------------------
# Bootstrap path so `bot` package resolves when running from this directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from bot.config import BOT_TOKEN, DATA_PATH, GUILD_IDS, OWNER_GUILD_ID, OWNER_IDS, SQLITE_PATH
from bot.features.onboarding import TermsGateView, build_terms_embed, has_user_accepted_terms
from bot.data.storage import Storage
from bot.data.sqlite_store import SQLiteBattleRepository, SQLiteMarketRepository, SQLiteTradeRepository
from bot.services.battle_service import BattleService
from bot.services.market_service import MarketService
from bot.services.trade_service import TradeService
from bot.utils.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All feature cogs to load
# ---------------------------------------------------------------------------
EXTENSIONS = [
    "bot.features.onboarding",
    "bot.features.profile",
    "bot.features.profile_owner",
    "bot.features.economy",
    "bot.features.inventory",
    "bot.features.packs",
    "bot.features.cards_admin",
    "bot.features.card_tools",
    "bot.features.market",
    "bot.features.market_owner",
    "bot.features.trades",
    "bot.features.rewards",
    "bot.features.owner_rewards",
    "bot.features.redeem",
    "bot.features.shop",
    "bot.features.squad",
    "bot.features.battle",
    "bot.features.tutorial",
    "bot.features.tournament",
    "bot.features.leaderboards",
    "bot.features.league_overview",
    "bot.features.achievements",
    "bot.features.season",
    "bot.features.alliance",
    "bot.features.gangs",
    "bot.features.server_settings",
    "bot.features.announce_owner",
    "bot.features.attacks_owner",
    "bot.features.confirm",
    "bot.features.packs_panel",
    "bot.features.emoji_panel",
    "bot.features.gang_war",
    "bot.features.stats_guide",
]


# ---------------------------------------------------------------------------
# Bot subclass
# ---------------------------------------------------------------------------
class LookismBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            owner_ids=OWNER_IDS,
            help_command=None,
            tree_cls=LookismCommandTree,
        )
        self.storage = Storage(DATA_PATH)
        # In-memory set of user IDs who have accepted terms — avoids a
        # storage.load() + deepcopy on every slash-command interaction.
        # Populated lazily on first cache miss; invalidated via mark_terms_accepted().
        self._terms_cache: set[int] = set()
        self.market_repo = SQLiteMarketRepository(SQLITE_PATH)
        self.market_service = MarketService(self.market_repo, self.storage)
        self.market_service.bootstrap_from_json()
        self.trade_repo = SQLiteTradeRepository(SQLITE_PATH)
        self.trade_service = TradeService(self.trade_repo, self.storage)
        self.trade_service.bootstrap_from_json()
        self.battle_repo = SQLiteBattleRepository(SQLITE_PATH)
        self.battle_service = BattleService(self.battle_repo, self.storage)
        self.battle_service.bootstrap_from_json()

    def mark_terms_accepted(self, user_id: int) -> None:
        """Called by onboarding code when a user accepts the ToS."""
        self._terms_cache.add(int(user_id))

    async def _unlock_stale_trades(self) -> None:
        """On startup, unlock any cards that were left trade_locked after a crash."""
        def mutate(data: dict[str, Any]) -> int:
            unlocked = 0
            for pid, player in data.get("players", {}).items():
                if not isinstance(player, dict):
                    continue
                user = player.get("user", {})
                if not isinstance(user, dict):
                    continue
                inv = user.get("inventory", [])
                if not isinstance(inv, list):
                    continue
                for item in inv:
                    if isinstance(item, dict) and item.get("trade_locked"):
                        item["trade_locked"] = False
                        unlocked += 1
            # Also clear pending trade records
            trades = data.get("trades", {})
            if isinstance(trades, dict):
                trades["pending"] = {}
            return unlocked

        count = self.storage.with_lock(mutate)
        if count:
            logger.warning("[BOOT] Unlocked %d cards left trade_locked from a previous crash.", count)

    async def _global_terms_gate(self, interaction: discord.Interaction) -> bool:
        command = getattr(interaction, "command", None)
        if command is None:
            return True

        # Autocomplete interactions can only be answered with response type 8
        # (autocomplete result). Sending an embed/message here raises a 400.
        # Let autocomplete through; the actual command invocation will still be
        # gated below.
        if interaction.type is discord.InteractionType.autocomplete:
            return True

        user_id = int(interaction.user.id)
        if user_id in self._terms_cache:
            return True

        data = self.storage.load()
        if has_user_accepted_terms(data, str(user_id)):
            self._terms_cache.add(user_id)
            return True

        embed = build_terms_embed()
        view = TermsGateView(self, interaction.user.id)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except discord.NotFound:
            pass
        return False

    async def setup_hook(self) -> None:
        """Load all cogs and sync slash commands."""
        failed: list[str] = []
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info("[BOOT] Loaded extension: %s", ext)
            except Exception as exc:
                logger.exception("[BOOT] Failed to load extension %s: %s", ext, exc)
                failed.append(ext)

        if failed:
            logger.warning("[BOOT] %d extension(s) failed to load: %s", len(failed), failed)
            # Keep the bot alive even if non-critical cogs fail — operators can
            # inspect logs and hot-reload the broken extension once the issue is fixed.

        # Sync slash commands
        owner_guild = discord.Object(id=OWNER_GUILD_ID)

        # Optional one-time cleanup for stale global command registry.
        # Set HXCC_CLEAR_GLOBAL_COMMANDS_ONCE=1 for a single startup run, then unset it.
        if os.getenv("HXCC_CLEAR_GLOBAL_COMMANDS_ONCE") == "1":
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("[BOOT] Cleared and synced empty global command registry.")

        if GUILD_IDS:
            for gid in GUILD_IDS:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("[BOOT] Synced commands to guild %s", gid)

        # Sync owner-guild-only commands (o_ commands registered via @app_commands.guilds(OWNER_GUILD)).
        # Do NOT use copy_global_to here — that would push all 100+ global commands into the guild.
        await self.tree.sync(guild=owner_guild)
        logger.info("[BOOT] Synced owner-guild commands to guild %s", OWNER_GUILD_ID)

        # Sync global public command registry (excludes o_ commands, which are guild-scoped).
        await self.tree.sync()
        logger.info("[BOOT] Synced commands globally.")

        self._log_registered_slash_commands()

        # Unlock any cards left trade_locked from a crash
        await self._unlock_stale_trades()

    def _log_registered_slash_commands(self) -> None:
        commands_list = self.tree.get_commands()
        logger.info("=== REGISTERED SLASH COMMANDS ===")
        total = 0

        def walk(cmd: object, parent: str = "") -> None:
            nonlocal total
            name = getattr(cmd, "name", "")
            if not name:
                return
            line = f"{parent} {name}" if parent else f"/{name}"
            logger.info(line)
            total += 1
            children = getattr(cmd, "commands", None)
            if children:
                for sub in children:
                    walk(sub, line)

        for command in commands_list:
            walk(command)
        logger.info("=== TOTAL COMMANDS: %d ===", total)

    async def on_ready(self) -> None:
        logger.info("[READY] Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        activity = discord.Activity(type=discord.ActivityType.watching, name="Lookism | /help")
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        logger.warning("[CMD_ERROR] %s: %s", ctx.command, error)


class LookismCommandTree(app_commands.CommandTree["LookismBot"]):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(self.client, LookismBot):
            return True
        return await self.client._global_terms_gate(interaction)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Command on cooldown. Try again in **{error.retry_after:.0f}s**."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except discord.HTTPException:
                pass
            return
        await super().on_error(interaction, error)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    bot = LookismBot()
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
