"""Entry point for Lookism Bot v2."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import discord
from discord.ext import commands

# ---------------------------------------------------------------------------
# Bootstrap path so `bot` package resolves when running from this directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from bot.config import BOT_TOKEN, DATA_PATH, SQLITE_PATH, assert_runtime_config
from bot.features.onboarding import TermsGateView, build_terms_embed, has_user_accepted_terms
from bot.data.storage import Storage
from bot.data.sqlite_store import SQLiteBattleRepository, SQLiteMarketRepository, SQLiteTradeRepository
from bot.services.battle_service import BattleService
from bot.services.market_service import MarketService
from bot.services.trade_service import TradeService
from bot.utils.checks import effective_owner_ids
from bot.utils.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Marker file used to distinguish clean shutdown from crash recovery.
# Present after a graceful close(); absent means the previous process
# died without running the shutdown path.
CLEAN_SHUTDOWN_MARKER = os.path.join(os.path.dirname(DATA_PATH), ".clean_shutdown")

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
    "bot.features.stats_preview",
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
    "bot.features.achievements",
    "bot.features.season",
    "bot.features.alliance",
    "bot.features.gangs",
    "bot.features.server_settings",
    "bot.features.announce_owner",
    "bot.features.attacks_owner",
    "bot.features.moderation_owner",
    "bot.features.confirm",
    "bot.features.packs_panel",
    "bot.features.emoji_panel",
    "bot.features.gang_war",
    "bot.features.keystones",
    "bot.features.weapons",
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
            owner_ids=effective_owner_ids(),
            help_command=None,
        )
        self.storage = Storage(DATA_PATH)
        # In-memory set of user IDs who have accepted terms — avoids a
        # storage.load() + deepcopy on every slash-command interaction.
        # Populated lazily on first cache miss; invalidated via mark_terms_accepted().
        self._terms_cache: set[int] = set()
        self.market_repo = SQLiteMarketRepository(SQLITE_PATH)
        self.market_service = MarketService(self.market_repo, self.storage)
        self.trade_repo = SQLiteTradeRepository(SQLITE_PATH)
        self.trade_service = TradeService(self.trade_repo, self.storage)
        self.battle_repo = SQLiteBattleRepository(SQLITE_PATH)
        self.battle_service = BattleService(self.battle_repo, self.storage)

    def mark_terms_accepted(self, user_id: int) -> None:
        """Called by onboarding code when a user accepts the ToS."""
        self._terms_cache.add(int(user_id))

    def invalidate_terms_cache(self, user_id: int) -> None:
        """Drop a user from the in-memory ToS cache.

        Call this whenever a user record is banned, reset, or wiped so
        that the next command re-consults storage instead of trusting a
        stale cached acceptance.
        """
        try:
            self._terms_cache.discard(int(user_id))
        except (TypeError, ValueError):
            pass

    async def _unlock_stale_trades(self) -> None:
        """On startup, decide between clean-shutdown vs. crash recovery.

        Clean shutdown (marker file present): trust on-disk state, do not
        touch pending trades or trade_locked flags — just delete the marker
        so the next boot can detect a crash.

        Crash recovery (marker missing): only clear trade_locked flags on
        inventory items so cards aren't stranded. Pending trades are left
        intact; a crashed process is not a reason to destroy legitimate
        in-flight offers.
        """
        clean_shutdown = os.path.exists(CLEAN_SHUTDOWN_MARKER)
        if clean_shutdown:
            try:
                os.remove(CLEAN_SHUTDOWN_MARKER)
            except OSError as exc:
                logger.warning("[BOOT] Could not remove clean-shutdown marker: %s", exc)
            logger.info("[BOOT] Clean shutdown detected; preserving pending trades and locks.")
            return

        def mutate(data: dict[str, Any]) -> int:
            unlocked = 0
            for _pid, player in data.get("players", {}).items():
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
            return unlocked

        count = self.storage.with_lock(mutate)
        logger.warning(
            "[BOOT] Crash recovery: cleared trade_locked on %d inventory item(s); pending trades preserved.",
            count,
        )

    def _write_clean_shutdown_marker(self) -> None:
        """Best-effort write of the clean-shutdown marker file."""
        try:
            os.makedirs(os.path.dirname(CLEAN_SHUTDOWN_MARKER), exist_ok=True)
            with open(CLEAN_SHUTDOWN_MARKER, "w", encoding="utf-8") as fh:
                fh.write("ok")
        except OSError as exc:
            logger.warning("[SHUTDOWN] Could not write clean-shutdown marker: %s", exc)

    async def close(self) -> None:
        """Override to drop the clean-shutdown marker before disconnecting."""
        self._write_clean_shutdown_marker()
        await super().close()

    async def _global_terms_gate(self, obj: Any) -> bool:
        """Check if the user has accepted the Terms of Service.

        Accepts both discord.Interaction and commands.Context.
        Returns False and sends the terms embed if not accepted.
        """
        user = getattr(obj, "user", None) or getattr(obj, "author", None)
        if user is None:
            return True

        user_id = int(user.id)
        if user_id in self._terms_cache:
            return True

        data = self.storage.load()
        if has_user_accepted_terms(data, str(user_id)):
            self._terms_cache.add(user_id)
            return True

        embed = build_terms_embed()
        view = TermsGateView(self, user_id)

        # Context path (prefix command)
        if not hasattr(obj, "response"):
            try:
                await obj.author.send(embed=embed, view=view)
            except discord.HTTPException:
                pass
            return False

        # Interaction path (legacy)
        try:
            if obj.response.is_done():
                await obj.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await obj.response.send_message(embed=embed, view=view, ephemeral=True)
        except discord.NotFound:
            pass
        return False

    async def setup_hook(self) -> None:
        """Load all cogs and bootstrap services."""
        # Bootstrap SQLite repos from JSON (must run before cogs start handling commands)
        await self.market_service.bootstrap_from_json()
        await self.trade_service.bootstrap_from_json()
        await self.battle_service.bootstrap_from_json()

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
            raise RuntimeError(f"Failed to load required extension(s): {failed}")

        # Unlock any cards left trade_locked from a crash
        await self._unlock_stale_trades()

        battle_cog = self.get_cog("BattleCog")
        if battle_cog is not None and hasattr(battle_cog, "recover_active_battles_after_restart"):
            summary = await battle_cog.recover_active_battles_after_restart()
            logger.info(
                "[BOOT] Battle startup recovery finished ended=%s cleared=%s active_by_user=%s affected_users=%s",
                summary.get("ended", 0),
                summary.get("cleared", 0),
                summary.get("active_by_user", 0),
                summary.get("affected_users", 0),
            )

    async def bot_check(self, ctx: commands.Context) -> bool:
        """Global check that runs before every prefix command.

        Enforces terms-of-service acceptance and channel locking.
        """
        if not await self._global_terms_gate(ctx):
            return False

        from bot.utils.server_rules import check_single_mode_allowed, is_admin
        from bot.utils.ui import e, make_embed

        command_name = str(ctx.command.name) if ctx.command else ""
        if command_name.startswith(("o_", "server_")) or command_name in {"help", "start"}:
            return True
        if is_admin(ctx):
            return True

        allowed, _mode, locked_channel_id = check_single_mode_allowed(ctx)
        if allowed:
            return True

        data = self.storage.load_readonly()
        embed = make_embed(
            data,
            f"{e('warning', data)} Wrong Channel",
            f"Use <#{locked_channel_id}> for bot commands.",
        )
        await ctx.send(embed=embed)
        return False

    async def on_ready(self) -> None:
        logger.info("[READY] Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        activity = discord.Activity(type=discord.ActivityType.watching, name="Lookism | !help")
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        logger.warning("[CMD_ERROR] %s: %s", ctx.command, error)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    assert_runtime_config()
    bot = LookismBot()
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
