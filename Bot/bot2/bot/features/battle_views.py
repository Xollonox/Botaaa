"""Battle UI views — Discord select menus and views for the battle system."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from bot.utils.ui import e, make_embed, style_view
from bot.utils.interaction_visibility import smart_reply
from bot.features.battle_helpers import (
    battle_warn,
    defer_component_update,
)

logger = logging.getLogger(__name__)


class AttackSelect(discord.ui.Select):
    """Select menu for choosing an offensive move."""

    def __init__(self, cog: commands.Cog, battle_id: str, actor_id: str, options: list[discord.SelectOption]) -> None:
        safe_options = options[:25] if options else [discord.SelectOption(label="⚪ No attack options", value="none")]
        super().__init__(
            placeholder="⚔️ Choose offensive move",
            min_values=1, max_values=1,
            options=safe_options, row=0,
            disabled=not bool(options),
        )
        self.cog = cog
        self.battle_id = battle_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if self.values and self.values[0] == "none":
                await defer_component_update(interaction)
                return
            await defer_component_update(interaction)
            actual_actor = str(interaction.user.id)
            await self.cog.resolve_selected_attack(interaction, self.battle_id, actual_actor, self.values[0])
        except Exception:
            logger.exception("[BATTLE_CALLBACK_ERROR] battle_id=%s actor=%s", self.battle_id, self.actor_id)
            data = self.cog.bot.storage.load()
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Battle State Error", "A battle state error occurred."),
                ephemeral=True,
            )


class DefenseSelect(discord.ui.Select):
    """Select menu for choosing a defensive move."""

    def __init__(self, cog: commands.Cog, battle_id: str, actor_id: str, options: list[discord.SelectOption]) -> None:
        safe_options = options[:25] if options else [discord.SelectOption(label="🛡 No defensive options", value="none")]
        super().__init__(
            placeholder="🛡 Choose Defence",
            min_values=1, max_values=1,
            options=safe_options, row=1,
            disabled=not bool(options),
        )
        self.cog = cog
        self.battle_id = battle_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if self.values and self.values[0] == "none":
                await defer_component_update(interaction)
                return
            await defer_component_update(interaction)
            actual_actor = str(interaction.user.id)
            await self.cog.resolve_selected_attack(interaction, self.battle_id, actual_actor, self.values[0])
        except Exception:
            logger.exception("[BATTLE_CALLBACK_ERROR] battle_id=%s actor=%s", self.battle_id, self.actor_id)
            data = self.cog.bot.storage.load()
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Battle State Error", "A battle state error occurred."),
                ephemeral=True,
            )


class SwitchSelect(discord.ui.Select):
    """Select menu for switching active fighter."""

    def __init__(self, cog: commands.Cog, battle_id: str, actor_id: str, options: list[discord.SelectOption]) -> None:
        safe_options = options[:25] if options else [discord.SelectOption(label="🔁 No switch options", value="none")]
        super().__init__(
            placeholder="🔄 Switch active fighter",
            min_values=1, max_values=1,
            options=safe_options, row=2,
            disabled=not bool(options),
        )
        self.cog = cog
        self.battle_id = battle_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if self.values and self.values[0] == "none":
                await defer_component_update(interaction)
                return
            await defer_component_update(interaction)
            actual_actor = str(interaction.user.id)
            await self.cog.resolve_move(interaction, self.battle_id, actual_actor, "switch", self.values[0])
        except Exception:
            logger.exception("[BATTLE_CALLBACK_ERROR] battle_id=%s actor=%s", self.battle_id, self.actor_id)
            data = self.cog.bot.storage.load()
            await battle_warn(
                interaction,
                make_embed(data, f"{e('warning', data)} Battle State Error", "A battle state error occurred."),
            )


class ForfeitButton(discord.ui.Button):
    """Button for forfeiting a match."""

    def __init__(self, cog: commands.Cog, battle_id: str, actor_id: str) -> None:
        super().__init__(
            label="🏳️ Forfeit",
            style=discord.ButtonStyle.danger,
            row=3,
        )
        self.cog = cog
        self.battle_id = battle_id
        self.actor_id = actor_id

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await defer_component_update(interaction)
            await self.cog.forfeit_internal(interaction, self.actor_id)
        except Exception:
            logger.exception("[BATTLE_FORFEIT_ERROR] battle_id=%s actor=%s", self.battle_id, self.actor_id)
            data = self.cog.bot.storage.load()
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Battle State Error", "A battle state error occurred."),
                ephemeral=True,
            )


class TurnView(discord.ui.View):
    """Main battle turn view with attack, defense, switch, and forfeit controls."""

    def __init__(
        self,
        cog: commands.Cog,
        battle_id: str,
        actor_id: str,
        attack_options: list[discord.SelectOption],
        defense_options: list[discord.SelectOption],
        switch_options: list[discord.SelectOption],
        enemy_id: str = "",
    ) -> None:
        # Battle expiry is controlled by BattleCog turn timers. Discord view
        # timeouts can disable a stale view and overwrite the live battle panel.
        super().__init__(timeout=None)
        self.cog = cog
        self.battle_id = battle_id
        self.actor_id = actor_id
        self.enemy_id = enemy_id
        self.message: discord.Message | None = None

        self.add_item(AttackSelect(cog, battle_id, actor_id, attack_options))
        self.add_item(DefenseSelect(cog, battle_id, actor_id, defense_options))
        self.add_item(SwitchSelect(cog, battle_id, actor_id, switch_options))
        self.add_item(ForfeitButton(cog, battle_id, actor_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        data = self.cog.bot.storage.load()
        battle = self.cog._battle_root(data).get("active", {}).get(self.battle_id)
        if not isinstance(battle, dict):
            await battle_warn(
                interaction,
                make_embed(data, f"{e('warning', data)} Battle Ended", "This battle no longer exists."),
            )
            return False
        players = battle.get("players", {}) if isinstance(battle.get("players"), dict) else {}
        allowed_users = {str(pid) for pid in players.keys()}
        if str(interaction.user.id) not in allowed_users:
            await battle_warn(
                interaction,
                make_embed(data, f"{e('warning', data)} Not Your Battle", "This battle panel doesn't belong to you."),
            )
            return False
        return True

    async def on_timeout(self) -> None:
        logger.info("[BATTLE_VIEW_TIMEOUT] ignored persistent battle view timeout battle_id=%s", self.battle_id)


class FriendlyInviteView(discord.ui.View):
    """View with Accept/Decline buttons for a friendly challenge."""

    def __init__(self, cog: commands.Cog, challenger_id: str, target_id: str) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.challenger_id = challenger_id
        self.target_id = target_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.target_id:
            data = self.cog.bot.storage.load()
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Not Your Invite", "Only the challenged player can respond to this invite."),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.accept_friendly(interaction, self.challenger_id, self.target_id)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        def mutate(data: dict[str, Any]) -> None:
            pending = self.cog._battle_root(data).get("pending_friendly", {})
            if isinstance(pending, dict):
                pending.pop(self.target_id, None)

        self.cog.bot.storage.with_lock(mutate)
        t = self.cog.friendly_cpu_tasks.pop(self.target_id, None)
        if t and not t.done():
            t.cancel()
        data = self.cog.bot.storage.load()
        await smart_reply(
            interaction,
            embed=make_embed(data, f"{e('no', data)} Challenge Declined", "The friendly challenge has been declined."),
            ephemeral=True,
        )


class RankedQueueView(discord.ui.View):
    """View with CPU Battle / Forfeit buttons for the ranked queue."""

    def __init__(self, cog: commands.Cog, user_id: str) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = str(user_id)
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            data = self.cog.bot.storage.load()
            await smart_reply(
                interaction,
                embed=make_embed(data, f"{e('warning', data)} Not Your Queue", "Only the queued player can use these buttons."),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                logger.exception("[RANKED_QUEUE_VIEW_TIMEOUT] failed to disable queue view user=%s", self.user_id)

    @discord.ui.button(label="CPU Battle", style=discord.ButtonStyle.primary, row=0)
    async def cpu_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await defer_component_update(interaction)
        except Exception:
            return
        ok = await self.cog._start_ranked_cpu_battle(interaction, self.user_id)
        if ok:
            for item in self.children:
                item.disabled = True
            if interaction.message is not None:
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    logger.exception("[RANKED_QUEUE_VIEW] failed to disable CPU button view user=%s", self.user_id)

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, row=0)
    async def forfeit_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await defer_component_update(interaction)
        except Exception:
            return
        ok = await self.cog._leave_ranked_queue(interaction, self.user_id, message="You've forfeited the ranked queue.")
        if ok:
            for item in self.children:
                item.disabled = True
            if interaction.message is not None:
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    logger.exception("[RANKED_QUEUE_VIEW] failed to disable forfeit view user=%s", self.user_id)
