"""Entry point for Lookism Bot v2."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
import time
from collections import defaultdict, deque
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

# ---------------------------------------------------------------------------
# Bootstrap path so `bot` package resolves when running from this directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from bot.config import (
    BOT_TOKEN,
    DATA_PATH,
    FIREBASE_CREDENTIALS_JSON,
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_PROJECT_ID,
    OWNER_GUILD_ID,
    assert_runtime_config,
)
from bot.features.onboarding import TermsGateView, build_terms_embed, has_user_accepted_terms
from bot.data.firestore_client import get_firestore_client
from bot.data.firestore_storage import FirestoreStorage
from bot.data.firestore_battle_repo import FirestoreBattleRepository
from bot.data.firestore_market_repo import FirestoreMarketRepository
from bot.data.firestore_trade_repo import FirestoreTradeRepository
from bot.services.battle_service import BattleService
from bot.services.market_service import MarketService
from bot.services.trade_service import TradeService
from bot.utils.checks import effective_owner_ids
from bot.utils.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Marker file for one-shot global commands clear.
# Prevents re-running the clear on every restart if HXCC_CLEAR_GLOBAL_COMMANDS_ONCE is left set.
CLEARED_GLOBAL_COMMANDS_MARKER = os.path.join(os.path.dirname(DATA_PATH), ".cleared_global_commands")


# ---------------------------------------------------------------------------
# One-shot clear global commands helpers
# ---------------------------------------------------------------------------
def _get_env_token(env_value: str) -> str:
    """Compute a stable hash token for the current env value."""
    return hashlib.sha256(env_value.encode("utf-8")).hexdigest()[:16]


def _should_clear_global_commands() -> bool:
    """Check if global commands should be cleared based on env and marker file.

    Returns True if:
    - Env var is set AND marker doesn't exist (first run)
    - Env var is set AND marker exists but with different token (value changed)

    Returns False if:
    - Env var not set
    - Env var is set AND marker exists with matching token (already cleared for this value)
    """
    env_value = os.getenv("HXCC_CLEAR_GLOBAL_COMMANDS_ONCE", "").strip()

    if not env_value:
        return False

    current_token = _get_env_token(env_value)

    # If marker exists, check if token matches
    if os.path.isfile(CLEARED_GLOBAL_COMMANDS_MARKER):
        try:
            with open(CLEARED_GLOBAL_COMMANDS_MARKER, "r", encoding="utf-8") as fh:
                stored_token = fh.read().strip()
            if stored_token == current_token:
                logger.info(
                    "[BOOT] Global commands already cleared for this env value (token: %s). Skipping.",
                    current_token
                )
                return False
        except OSError as exc:
            logger.warning("[BOOT] Could not read global commands marker: %s", exc)

    return True


def _write_global_commands_marker(env_value: str) -> None:
    """Write marker file with a token of the current env value."""
    try:
        os.makedirs(os.path.dirname(CLEARED_GLOBAL_COMMANDS_MARKER), exist_ok=True)
        token = _get_env_token(env_value)
        with open(CLEARED_GLOBAL_COMMANDS_MARKER, "w", encoding="utf-8") as fh:
            fh.write(token)
        logger.info("[BOOT] Wrote global commands marker with token: %s", token)
    except OSError as exc:
        logger.warning("[BOOT] Could not write global commands marker: %s", exc)

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
    "bot.features.moderation_owner",
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
            tree_cls=LookismCommandTree,
        )
        firestore_client = get_firestore_client(
            FIREBASE_PROJECT_ID, FIREBASE_CREDENTIALS_PATH, FIREBASE_CREDENTIALS_JSON
        )
        self.storage = FirestoreStorage(firestore_client)
        # In-memory set of user IDs who have accepted terms — avoids a
        # storage.load() + deepcopy on every slash-command interaction.
        # Populated lazily on first cache miss; invalidated via mark_terms_accepted().
        self._terms_cache: set[int] = set()
        self.market_repo = FirestoreMarketRepository(firestore_client)
        self.market_service = MarketService(self.market_repo, self.storage)
        self.trade_repo = FirestoreTradeRepository(firestore_client)
        self.trade_service = TradeService(self.trade_repo, self.storage)
        self.battle_repo = FirestoreBattleRepository(firestore_client)
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
        """Clear non-persistent trade panels while preserving live board offers."""
        live_offers = await self.trade_service.get_open_offers(limit=10_000)
        live_locks = {
            (str(row.get("poster_id", "")), str(row.get("item_uid", "")))
            for row in live_offers
        }
        pending_count = await self.trade_service.clear_pending()

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
                    lock_key = (str(_pid), str(item.get("uid", ""))) if isinstance(item, dict) else ("", "")
                    if isinstance(item, dict) and item.get("trade_locked") and lock_key not in live_locks:
                        item["trade_locked"] = False
                        unlocked += 1
            data.setdefault("trades", {})["pending"] = {}
            return unlocked

        count = await self.storage.with_lock(mutate)
        logger.warning(
            "[BOOT] Trade recovery: cleared %d transient pending row(s) and unlocked %d card(s).",
            pending_count,
            count,
        )

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

        data = await self.storage.load()
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

    async def _global_restriction_gate(self, interaction: discord.Interaction) -> bool:
        """Enforce game-level bans and mutes for every slash command."""
        from bot.utils.ui import e, make_embed

        data = self.storage.load_readonly()
        player = data.get("players", {}).get(str(interaction.user.id), {})
        user = player.get("user", {}) if isinstance(player, dict) else {}
        if not isinstance(user, dict):
            return True
        restriction = None
        if bool(user.get("is_banned", False)):
            restriction = ("Banned", str(user.get("ban_reason", "No reason provided.")))
        elif bool(user.get("is_muted", False)):
            restriction = ("Muted", str(user.get("mute_reason", "No reason provided.")))
        if restriction is None:
            return True
        label, reason = restriction
        embed = make_embed(
            data,
            f"{e('no', data)} You Are {label}",
            f"You cannot use bot commands right now.\n**Reason:** {reason}",
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass
        return False

    async def setup_hook(self) -> None:
        """Load all cogs and sync slash commands."""
        # Bootstrap Firestore repos from legacy JSON on first boot (idempotent).
        # Must run before cogs start handling commands.
        await self.market_service.bootstrap_from_json()
        await self.trade_service.bootstrap_from_json()
        await self.battle_service.bootstrap_from_json()

        # Re-open any offers left in 'processing' state by a prior crash.
        # Kept off __init__ so bot construction can't block on Firestore I/O.
        await self.trade_repo.recover_stale_processing_offers()

        # Warm the Firestore-backed storage cache so the first user interaction
        # doesn't pay the hydrate round-trip inside Discord's 3s ack window
        # (cold cache + slow first read used to kill interactions with 10062).
        await asyncio.get_running_loop().run_in_executor(None, self.storage.load)
        logger.info("[BOOT] Storage cache warmed")

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

        # Sync slash commands
        owner_guild = discord.Object(id=OWNER_GUILD_ID)

        # Optional one-time cleanup for stale global command registry.
        # Set HXCC_CLEAR_GLOBAL_COMMANDS_ONCE=1 to trigger a wipe. On success, a marker file
        # is written with a token of the env value. Subsequent restarts with the same env value
        # will skip the wipe (idempotent). If the env value changes, the wipe runs again.
        if _should_clear_global_commands():
            env_value = os.getenv("HXCC_CLEAR_GLOBAL_COMMANDS_ONCE", "").strip()
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            _write_global_commands_marker(env_value)
            logger.info("[BOOT] Cleared and synced empty global command registry.")

        # Sync owner-guild-only commands (o_ commands registered via @app_commands.guilds(OWNER_GUILD)).
        # Do NOT use copy_global_to here — that would push all 100+ global commands into the guild.
        await self.tree.sync(guild=owner_guild)
        logger.info("[BOOT] Synced owner-guild commands to guild %s", OWNER_GUILD_ID)

        # Sync global public command registry (excludes o_ commands, which are guild-scoped).
        await self.tree.sync()
        logger.info("[BOOT] Synced commands globally.")

        self._log_registered_slash_commands()

        # Unlock any cards left trade_locked from a crash. Runs in the
        # background so a full-players scan can't stall setup_hook and push
        # Discord's connect handshake past its grace period.
        task = asyncio.create_task(self._unlock_stale_trades())
        task.add_done_callback(
            lambda t: logger.exception(
                "[BOOT] Stale-trade unlock failed: %s", t.exception()
            ) if t.exception() else None
        )

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
        activity = discord.Activity(type=discord.ActivityType.watching, name="Lookism CG | /help")
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        logger.warning("[CMD_ERROR] %s: %s", ctx.command, error)


class LookismCommandTree(app_commands.CommandTree["LookismBot"]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._command_times: dict[int, deque[float]] = defaultdict(deque)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(self.client, LookismBot):
            return True
        if interaction.type is discord.InteractionType.autocomplete:
            return True

        # Rate limit FIRST — the restriction/terms gates below can cost a full
        # storage.load() deepcopy for uncached users, so throttling must run
        # before any gate can reject an interaction.
        now = time.monotonic()
        user_times = self._command_times[int(interaction.user.id)]
        while user_times and now - user_times[0] >= 10.0:
            user_times.popleft()
        if len(user_times) >= 5:
            retry_after = max(0.1, 10.0 - (now - user_times[0]))
            try:
                await interaction.response.send_message(
                    f"⏳ Too many commands. Try again in **{retry_after:.1f}s**.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
            return False
        user_times.append(now)
        # Bound the per-user deque map so it can't grow forever.
        if len(self._command_times) > 10_000:
            for stale_uid in [uid for uid, dq in self._command_times.items() if not dq]:
                self._command_times.pop(stale_uid, None)

        if not await self.client._global_restriction_gate(interaction):
            return False
        if not await self.client._global_terms_gate(interaction):
            return False

        from bot.utils.server_rules import check_single_mode_allowed, is_admin
        from bot.utils.ui import e, make_embed

        command = getattr(interaction, "command", None)
        command_name = str(getattr(command, "name", "") or "")
        if command_name.startswith(("o_", "server_")) or command_name in {"help", "start"}:
            return True
        if is_admin(interaction):
            return True

        allowed, _mode, locked_channel_id = check_single_mode_allowed(interaction)
        if allowed:
            return True

        # Read-only fast path: only passed to make_embed/e which read only.
        data = self.client.storage.load_readonly()
        embed = make_embed(
            data,
            f"{e('warning', data)} Wrong Channel",
            f"Use <#{locked_channel_id}> for bot commands.",
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass
        return False

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        # 10062 Unknown interaction — token died before the bot acked (client lag,
        # cold start, double-fire). Nothing can be replied to; log and move on.
        original = getattr(error, "original", error)
        if isinstance(original, discord.NotFound) and getattr(original, "code", None) == 10062:
            logger.warning(
                "[CMD] interaction expired before ack (command=%s user=%s)",
                getattr(interaction.command, "qualified_name", "?"),
                getattr(interaction.user, "id", "?"),
            )
            return
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
    assert_runtime_config()
    bot = LookismBot()
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
