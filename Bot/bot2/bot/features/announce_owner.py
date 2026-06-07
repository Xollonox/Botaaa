"""Owner manual announcement command and event management."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import random

from bot.config import OWNER_GUILD_ID
from bot.utils.checks import is_owner
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply
from bot.utils.timeutil import now_ts

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class AnnounceOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.card_of_the_day.start()
        self.weekly_bounty.start()

    def cog_unload(self) -> None:
        self.card_of_the_day.cancel()
        self.weekly_bounty.cancel()

    @tasks.loop(hours=24)
    async def card_of_the_day(self) -> None:
        """Background task: pick and announce Card of the Day every 24 hours."""
        data = self.bot.storage.load()
        cards = data.get("cards", {})
        if not isinstance(cards, dict) or not cards:
            return

        card_names = list(cards.keys())
        if not card_names:
            return

        selected = random.choice(card_names)
        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        data["cotd"] = {
            "card_name": selected,
            "date": today_str,
            "buff_pct": 15,
        }
        self.bot.storage.save(data)

        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        announce_channel_id = int(settings.get("announce_channel_id", 0) or 0)

        if announce_channel_id <= 0:
            return

        target_channel = self.bot.get_channel(announce_channel_id)
        if target_channel is None:
            try:
                target_channel = await self.bot.fetch_channel(announce_channel_id)
            except Exception:
                return

        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            return

        embed = make_embed(
            data,
            f"⚡ CARD OF THE DAY",
            f"**{selected}** gains **+15% damage** in all battles today!",
        )
        embed.set_footer(text=f"Rotation: {today_str}")
        try:
            await target_channel.send(embed=embed)
        except Exception:
            pass

    @card_of_the_day.before_loop
    async def before_card_of_the_day(self) -> None:
        """Wait for bot to be ready before starting the task."""
        await self.bot.wait_until_ready()

    @tasks.loop(hours=168)
    async def weekly_bounty(self) -> None:
        """Background task: pick player with highest win streak and announce bounty every 7 days."""
        data = self.bot.storage.load()
        players = data.get("players", {})
        if not isinstance(players, dict):
            return

        max_streak = 0
        target_id = None
        target_name = "Unknown"

        for uid, player in players.items():
            if not isinstance(player, dict):
                continue
            ranked_stats = player.get("ranked_stats", {})
            if not isinstance(ranked_stats, dict):
                continue
            streak = int(ranked_stats.get("streak", 0))
            if streak >= 5 and streak > max_streak:
                max_streak = streak
                target_id = str(uid)
                user = player.get("user", {})
                target_name = str(user.get("name", "Unknown")) if isinstance(user, dict) else "Unknown"

        if target_id is None or max_streak < 5:
            return

        week_num = (now_ts() // 604800)
        data["bounty"] = {
            "target_id": target_id,
            "target_name": target_name,
            "streak": max_streak,
            "reward": 3000,
            "week": week_num,
        }
        self.bot.storage.save(data)

        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        announce_channel_id = int(settings.get("announce_channel_id", 0) or 0)

        if announce_channel_id <= 0:
            return

        target_channel = self.bot.get_channel(announce_channel_id)
        if target_channel is None:
            try:
                target_channel = await self.bot.fetch_channel(announce_channel_id)
            except Exception:
                return

        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            return

        embed = make_embed(
            data,
            "🎯 WANTED: BOUNTY BOARD",
            f"**@{target_name}** is on a **{max_streak}-win streak**!\n\nFirst to beat them earns **3,000 bonus coins**!",
        )
        embed.set_footer(text="Bounty Board")
        try:
            await target_channel.send(embed=embed)
        except Exception:
            pass

    @weekly_bounty.before_loop
    async def before_weekly_bounty(self) -> None:
        """Wait for bot to be ready before starting the task."""
        await self.bot.wait_until_ready()

    @card_of_the_day.before_loop
    async def before_card_of_the_day(self) -> None:
        """Wait for bot to be ready before starting the task."""
        await self.bot.wait_until_ready()

    @app_commands.command(name="o_announce", description="Owner: manually post an announcement.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_announce(
        self,
        interaction: discord.Interaction,
        message: str,
        title: str | None = None,
        image_url: str | None = None,
        ping_role: discord.Role | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        announce_channel_id = int(settings.get("announce_channel_id", 0) or 0)

        target_channel = interaction.channel
        if announce_channel_id > 0:
            target_channel = self.bot.get_channel(announce_channel_id)
            if target_channel is None:
                try:
                    target_channel = await self.bot.fetch_channel(announce_channel_id)
                except Exception:
                    target_channel = interaction.channel

        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            await smart_reply(interaction,
                embed=make_embed(data, f"{e('warning', data)} Announcement Failed", "Target channel unavailable."),
                ephemeral=True,
            )
            return

        embed = make_embed(
            data,
            f"{e('announce', data)} {title.strip() if isinstance(title, str) and title.strip() else 'Announcement'}",
            str(message),
        )
        embed.set_footer(text="Server Announcement")
        if isinstance(image_url, str) and image_url.strip():
            embed.set_image(url=image_url.strip())

        content = ping_role.mention if ping_role is not None else None
        posted = await target_channel.send(content=content, embed=embed)

        await smart_reply(interaction,
            embed=make_embed(
                data,
                f"{e('ok', data)} Announcement Posted",
                f"{e('channel', data)} {target_channel.mention}\n{e('link', data)} {posted.jump_url}",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="o_event", description="Owner: activate double XP/coins event.")
    @app_commands.guilds(OWNER_GUILD)
    @app_commands.describe(
        event_type="Event type: double_xp or double_coins",
        duration_hours="Duration in hours",
    )
    async def o_event(
        self,
        interaction: discord.Interaction,
        event_type: str = "double_xp",
        duration_hours: int = 24,
    ) -> None:
        """Activate a timed event for double XP or coins."""
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        event_type = event_type.lower().strip()
        if event_type not in ("double_xp", "double_coins"):
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('no', data)} Invalid Event", "Use: double_xp or double_coins"),
                ephemeral=True,
            )
            return

        duration_hours = max(1, min(720, int(duration_hours)))  # clamp 1-730 hours
        ends_at = now_ts() + (duration_hours * 3600)

        events = data.setdefault("active_events", {})
        if not isinstance(events, dict):
            events = {}
            data["active_events"] = events

        events[event_type] = {
            "active": True,
            "ends_at": ends_at,
        }

        self.bot.storage.save(data)

        # Announce to the announcement channel
        settings = data.get("server_settings", {}) if isinstance(data.get("server_settings"), dict) else {}
        announce_channel_id = int(settings.get("announce_channel_id", 0) or 0)

        announce_text = "2x XP 🚀" if event_type == "double_xp" else "1.5x CP Rewards 💰"
        embed = make_embed(
            data,
            "🎉 EVENT ACTIVATED",
            f"{announce_text} for **{duration_hours}** hours!",
        )

        if announce_channel_id > 0:
            try:
                channel = self.bot.get_channel(announce_channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(announce_channel_id)
                if isinstance(channel, (discord.TextChannel, discord.Thread)):
                    await channel.send(embed=embed)
            except Exception:
                pass

        await smart_reply(
            interaction,
            embed=make_embed(
                data,
                f"{e('ok', data)} Event Started",
                f"{announce_text} for {duration_hours}h",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnounceOwnerCog(bot))

