"""Pack inventory panel — Free Fire-style animation, post-reveal browsing."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.ui import make_embed, e
from bot.utils.interaction_visibility import error_reply
from bot.features.packs import _get_player_pack_inventory, _open_pack_from_inventory
from bot.features.tutorial import advance_tutorial
from bot.utils.squad_logic import get_player, get_squad
from bot.utils.market_logic import quick_sell_value
from bot.utils.pack_logic import PITY_THRESHOLDS
from bot.utils.ui import e as _e

# Public exports for shop.py to reuse
__all__ = [
    "animate_pack_open",
    "_AnimView",
    "PostRevealView",
    "_anim_embed",
    "_card_reveal_embed",
    "RARITY_ICONS",
    "HIGH_RARITY",
]

RARITY_ICONS = {
    "common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟠", "mythical": "🔴", "infernal": "🔥", "abyssal": "🌌",
}
RARITY_RANK   = ["common", "rare", "epic", "legendary", "mythical", "infernal", "abyssal"]
HIGH_RARITY   = {"legendary", "mythical", "infernal", "abyssal"}
SELL_FALLBACK = {"common": 100, "rare": 300, "epic": 800,
                 "legendary": 2000, "mythical": 5000, "infernal": 8000, "abyssal": 12000}
logger = logging.getLogger(__name__)


def _ri(rarity: str) -> str:
    return RARITY_ICONS.get(str(rarity).lower(), "•")

def _rv(rarity: str) -> int:
    r = str(rarity).lower()
    return RARITY_RANK.index(r) if r in RARITY_RANK else 0


# ── Embed builders ────────────────────────────────────────────────

def _panel_embed(user_id: str, slot: int, pack_inv: list[dict[str, Any]], player: dict[str, Any] | None = None) -> discord.Embed:
    counts: dict[str, int] = {}
    names:  dict[str, str] = {}
    for item in pack_inv:
        k = str(item.get("key", ""))
        counts[k] = counts.get(k, 0) + 1
        names[k]  = str(item.get("name", k))

    keys  = list(counts.keys())
    total = len(pack_inv)
    overview = (
        "╭─ Pack Inventory\n"
        f"│ 📦 Total Packs: {total}\n"
        f"│ 🎴 Types: {len(keys)}\n"
        "╰────────────────"
    )

    if not keys:
        desc = overview + "\n\n╭─ No Packs\n│ Buy packs from /shop!\n╰────────────────"
        return make_embed(None, "LOOKISM HXCC • PACKS", desc, color=0xE11D48, footer="Pack Inventory")

    slot = max(0, min(slot, len(keys) - 1))

    # Collect pity info for the selected slot's pack key.
    pity_lines: dict[str, str] = {}
    if player is not None:
        user_data = player.get("user", {})
        pity_all = user_data.get("pity", {}) if isinstance(user_data, dict) else {}
        if isinstance(pity_all, dict):
            selected_key = keys[slot]
            thresholds = PITY_THRESHOLDS.get(selected_key, {})
            if thresholds:
                pity_counters = pity_all.get(selected_key, {})
                pity_parts = []
                for rarity, threshold in thresholds.items():
                    count = int(pity_counters.get(f"pulls_since_{rarity.lower()}", 0)) if isinstance(pity_counters, dict) else 0
                    pity_parts.append(f"{count}/{threshold} to guaranteed {rarity}")
                if pity_parts:
                    pity_lines[selected_key] = " • ".join(pity_parts)

    blocks = [overview]
    for i, k in enumerate(keys):
        marker = "👉 " if i == slot else ""
        pity_str = f"\n│ 🎯 Pity: {pity_lines[k]}" if k in pity_lines else ""
        blocks.append(
            f"╭─ {marker}{names[k]}\n│ Quantity: ×{counts[k]}\n│ Secret contents inside...{pity_str}\n╰────────────────"
        )

    return make_embed(None, "LOOKISM HXCC • PACKS", "\n\n".join(blocks), color=0xE11D48, footer=f"Pack Inventory • Slot {slot + 1}/{len(keys)}")


def _card_reveal_embed(roll: dict[str, str], idx: int, total: int, pack_name: str) -> discord.Embed:
    rarity = str(roll.get("rarity", "Common"))
    name   = str(roll.get("name", "Unknown"))
    icon   = _ri(rarity)
    colors = {"legendary": 0xF39C12, "mythical": 0xE74C3C, "infernal": 0xC0392B,
              "abyssal": 0x5B2C6F, "epic": 0x9B59B6, "rare": 0x3498DB}
    color  = colors.get(rarity.lower(), 0x2B2D31)

    body = (
        f"╭─ 🎴 {pack_name}  •  Card {idx}/{total}\n"
        f"│ {icon} {name}\n"
        f"│ [{rarity}]\n"
        "╰────────────────"
    )
    if rarity.lower() in HIGH_RARITY:
        sep   = "━" * 24
        body += f"\n\n{sep}\n  ⚠️  {rarity.upper()} PULL!\n{sep}"

    img = str(roll.get("image_url", "")).strip() or None
    return make_embed(None, "LOOKISM HXCC • PACKS", body, color=color, footer=f"Card {idx} of {total} • Pack Reveal", image_url=img)


def _anim_embed(title: str, slots: str, caption: str, color: int = 0xE11D48) -> discord.Embed:
    return make_embed(
        None, "LOOKISM HXCC • PACKS",
        f"╭─ {title}\n│ {slots}\n│ {caption}\n╰────────────────",
        color=color, footer="Opening...",
    )


async def animate_pack_open(
    msg: discord.Message,
    title: str,
    rolls: list[dict],
    data: dict,
    anim_view: "_AnimView",
) -> None:
    """Standalone Free Fire-style pack opening animation.

    Checks *anim_view.skipped* between every step so the Skip button works.
    """
    import asyncio

    build = [
        (0.4, "⬛  ⬛  ⬛  ⬛  ⬛", "Preparing your packs...",  0x2B2D31),
        (0.4, "🟥  🟥  🟥  🟥  🟥", "⚡ Energy charging...",    0xE74C3C),
        (0.4, "🔄  🔄  🔄  🔄  🔄", "💫 Cards spinning...",     0xE11D48),
    ]
    for delay, slots, caption, color in build:
        if anim_view.skipped:
            return
        await asyncio.sleep(delay)
        if anim_view.skipped:
            return
        try:
            await msg.edit(embed=_anim_embed(title, slots, caption, color))
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException:
            logger.warning("Failed to update pack animation", exc_info=True)
            return

    locked: list[str] = []
    display = rolls[:8]
    for i, roll in enumerate(display):
        if anim_view.skipped:
            return
        await asyncio.sleep(0.35)
        if anim_view.skipped:
            return
        locked.append(_ri(roll.get("rarity", "common")))
        remaining   = len(display) - len(locked)
        slot_row    = "  ".join(locked + [_e("switch", data)] * min(remaining, 5))
        rarity_name = str(roll.get("rarity", "")).title()
        caption     = f"🔒 {rarity_name} locked in!" if remaining > 0 else "🔄 Almost..."
        try:
            await msg.edit(embed=_anim_embed(title, slot_row, caption))
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException:
            logger.warning("Failed to update pack reveal animation", exc_info=True)
            return

    if anim_view.skipped:
        return
    await asyncio.sleep(0.5)
    if anim_view.skipped:
        return
    slot_row = "  ".join(locked)
    try:
        await msg.edit(embed=_anim_embed(title, slot_row, "✨  ✨  ✨  ✨  ✨"))
    except (discord.NotFound, discord.Forbidden):
        return
    except discord.HTTPException:
        logger.warning("Failed to finish pack animation", exc_info=True)
        return

    rarest = max(rolls, key=lambda r: _rv(r.get("rarity", "common")))
    if str(rarest.get("rarity", "")).lower() in HIGH_RARITY:
        if anim_view.skipped:
            return
        await asyncio.sleep(0.8)
        if anim_view.skipped:
            return
        sep   = "━" * 14
        alert = f"{sep}\n│ ⚠️  {str(rarest.get('rarity','')).upper()} DETECTED!\n│ {sep}"
        try:
            await msg.edit(embed=_anim_embed(title, slot_row, alert, 0xF39C12))
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException:
            logger.warning("Failed to show high-rarity pack alert", exc_info=True)
            return


# ── Post-reveal view (shown after opening) ────────────────────────

class PostRevealView(discord.ui.View):
    """Shown after opening — browse cards, quick sell, add to squad, back."""

    def __init__(self, cog: "PacksPanelCog", invoker_id: int,
                 rolls: list[dict[str, str]], pack_name: str,
                 main_panel: "PacksPanel") -> None:
        super().__init__(timeout=120)
        self.cog        = cog
        self.invoker_id = invoker_id
        self.rolls      = rolls
        self.pack_name  = pack_name
        self.main_panel = main_panel
        self.idx        = 0          # current card index (0-based)
        self.message: discord.Message | None = None
        # Relabel back button when returning to shop
        if hasattr(main_panel, '_shop_view'):
            for child in self.children:
                if isinstance(child, discord.ui.Button) and "Back to Packs" in str(getattr(child, "label", "")):
                    child.label = "← Back to Shop"
                    break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await error_reply(interaction, "Not your panel.")
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                logger.warning("Failed to disable post-reveal view after timeout", exc_info=True)

    def _current(self) -> dict[str, str]:
        return self.rolls[self.idx]

    # Row 0 — Card navigation
    @discord.ui.button(label="◀ Prev Card", style=discord.ButtonStyle.secondary, row=0)
    async def prev_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.idx = (self.idx - 1) % len(self.rolls)
        embed = _card_reveal_embed(self._current(), self.idx + 1, len(self.rolls), self.pack_name)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next Card ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.idx = (self.idx + 1) % len(self.rolls)
        embed = _card_reveal_embed(self._current(), self.idx + 1, len(self.rolls), self.pack_name)
        await interaction.response.edit_message(embed=embed, view=self)

    # Row 1 — Actions on current card
    @discord.ui.button(label="⚡ Quick Sell", style=discord.ButtonStyle.secondary, row=1)
    async def quick_sell_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        roll    = self._current()
        uid     = str(roll.get("uid", ""))
        rarity  = str(roll.get("rarity", "Common"))
        user_id = str(interaction.user.id)

        if not uid:
            await error_reply(interaction, "Card UID not found.")
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, int]:
            player = get_player(data, user_id)
            if not isinstance(player, dict):
                return False, 0
            user = player.get("user", {})
            inv  = user.get("inventory", []) if isinstance(user, dict) else []
            if not isinstance(inv, list):
                return False, 0
            idx = next((i for i, item in enumerate(inv)
                        if isinstance(item, dict)
                        and str(item.get("uid", "")) == uid
                        and not item.get("locked")
                        and not item.get("squad_locked")), None)
            if idx is None:
                return False, 0
            inv.pop(idx)
            value = quick_sell_value(data, rarity)
            if value <= 0:
                value = SELL_FALLBACK.get(rarity.lower(), 100)
            bal = int(user.get("balance", user.get("coins", 0)))
            user["balance"] = bal + value
            return True, value

        ok, value = self.cog.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, "Could not sell — card may be locked or already sold.")
            return

        # Remove from our rolls list so it can't be sold again
        self.rolls[self.idx]["_sold"] = True
        icon = _ri(rarity)
        body = (
            f"╭─ ⚡ Quick Sold!\n"
            f"│ {icon} {roll.get('name', '')}  [{rarity}]\n"
            f"│ 💰 +{value:,} coins\n"
            "╰────────────────"
        )
        e = make_embed(None, "LOOKISM HXCC • PACKS", body, color=0x2B2D31, footer=f"Card {self.idx + 1} of {len(self.rolls)} • Sold")
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="🪖 Add to Squad", style=discord.ButtonStyle.primary, row=1)
    async def add_squad_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        roll    = self._current()
        uid     = str(roll.get("uid", ""))
        user_id = str(interaction.user.id)

        if not uid:
            await error_reply(interaction, "Card UID not found.")
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            player = get_player(data, user_id)
            if not isinstance(player, dict):
                return False, "not_found"
            user = player.get("user", {})
            inv  = user.get("inventory", []) if isinstance(user, dict) else []
            if not isinstance(inv, list):
                return False, "invalid"

            squad  = get_squad(player)
            active = squad.get("active", [])
            backup = squad.get("backup", [])
            all_slots = [str(u) for u in active + backup if str(u)]

            if len(all_slots) >= 4:
                return False, "full"

            card = next((row for row in inv
                         if isinstance(row, dict) and str(row.get("uid", "")) == uid), None)
            if not isinstance(card, dict):
                return False, "missing"
            if uid in all_slots:
                return False, "exists"

            if len(active) < 2:
                active.append(uid)
                squad["active"] = active
            else:
                backup.append(uid)
                squad["backup"] = backup
            card["squad_locked"] = True
            return True, "ok"

        ok, status = self.cog.bot.storage.with_lock(mutate)
        if not ok:
            msgs = {"full": "Squad is full (4 slots max).", "exists": "Already in squad.",
                    "missing": "Card not found in inventory."}
            await interaction.response.send_message(msgs.get(status, "Could not add to squad."), ephemeral=True)
            return

        rarity = str(roll.get("rarity", ""))
        body = (
            f"╭─ 🪖 Added to Squad!\n"
            f"│ {_ri(rarity)} {roll.get('name', '')}  [{rarity}]\n"
            "│ Use /squad to manage your formation\n"
            "╰────────────────"
        )
        e = make_embed(None, "LOOKISM HXCC • PACKS", body, color=0x3498DB, footer=f"Card {self.idx + 1} of {len(self.rolls)} • Added")
        await interaction.response.edit_message(embed=e, view=self)

    # Row 2 — Back to pack panel (or shop if main_panel has _shop_view)
    @discord.ui.button(label="← Back to Packs", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        # If opened from shop flow, go back to shop
        if hasattr(self.main_panel, '_shop_view') and self.main_panel._shop_view is not None:
            shop_view: Any = self.main_panel._shop_view
            data = self.cog.bot.storage.load()
            shop_view._rebuild_selects()
            await interaction.response.edit_message(embed=shop_view.embed(data), view=shop_view)
            shop_view.message = interaction.message
            return
        data   = self.cog.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        inv    = _get_player_pack_inventory(player) if player else []
        uid    = str(interaction.user.id)
        embed  = _panel_embed(uid, self.main_panel.current_slot, inv, player)
        await interaction.response.edit_message(embed=embed, view=self.main_panel)
        self.main_panel.message = interaction.message


# ── Anim view ─────────────────────────────────────────────────────

class _AnimView(discord.ui.View):
    def __init__(self, panel: "PacksPanel") -> None:
        super().__init__(timeout=15)
        self.panel   = panel
        self.skipped = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.panel.invoker_id:
            await error_reply(interaction, "Not your panel.")
            return False
        return True

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.skipped = self.panel.skipped = True
        await interaction.response.defer()


class OpenQtyModal(discord.ui.Modal, title="Open Packs"):
    quantity = discord.ui.TextInput(label="How many to open?", placeholder="e.g. 3", min_length=1, max_length=3)

    def __init__(self, panel: "PacksPanel") -> None:
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            qty = int(str(self.quantity.value).strip())
            if qty < 1: raise ValueError
        except ValueError:
            await interaction.response.send_message("Enter a valid number.", ephemeral=True)
            return
        await self.panel._do_open(interaction, qty)


# ── Main panel ────────────────────────────────────────────────────

class PacksPanel(discord.ui.View):
    def __init__(self, cog: "PacksPanelCog", invoker_id: int) -> None:
        super().__init__(timeout=180)
        self.cog          = cog
        self.invoker_id   = invoker_id
        self.current_slot = 0
        self.skipped      = False
        self._anim_view: _AnimView | None = None
        self.message: discord.Message | None = None

    def _pack_keys(self, data: dict[str, Any]) -> list[str]:
        player = get_player(data, str(self.invoker_id))
        if not player: return []
        inv  = _get_player_pack_inventory(player)
        seen: list[str] = []
        for item in inv:
            k = str(item.get("key", ""))
            if k and k not in seen: seen.append(k)
        return seen

    def _current_key(self, data: dict[str, Any]) -> str | None:
        keys = self._pack_keys(data)
        if not keys: return None
        self.current_slot = max(0, min(self.current_slot, len(keys) - 1))
        return keys[self.current_slot]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("This pack panel belongs to another player.", ephemeral=True)
                else:
                    await interaction.response.send_message("This pack panel belongs to another player.", ephemeral=True)
            except discord.NotFound:
                pass
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"): child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass  # message was deleted
            except discord.Forbidden:
                pass  # bot lost access to channel
            except discord.HTTPException:
                logger.warning("Failed to disable packs panel after timeout", exc_info=True)

    # Row 0 — Nav
    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        keys = self._pack_keys(data)
        if keys: self.current_slot = (self.current_slot - 1) % len(keys)
        player = get_player(data, str(interaction.user.id))
        inv = _get_player_pack_inventory(player) if player else []
        await interaction.response.edit_message(embed=_panel_embed(str(interaction.user.id), self.current_slot, inv, player), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        keys = self._pack_keys(data)
        if keys: self.current_slot = (self.current_slot + 1) % len(keys)
        player = get_player(data, str(interaction.user.id))
        inv = _get_player_pack_inventory(player) if player else []
        await interaction.response.edit_message(embed=_panel_embed(str(interaction.user.id), self.current_slot, inv, player), view=self)

    # Row 1 — Open actions
    @discord.ui.button(label="📦 Open 1", style=discord.ButtonStyle.success, row=1)
    async def open_one(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._do_open(interaction, 1)

    @discord.ui.button(label="📦 Open All", style=discord.ButtonStyle.success, row=1)
    async def open_all_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        key  = self._current_key(data)
        if not key:
            await error_reply(interaction, "No packs to open.")
            return
        player = get_player(data, str(interaction.user.id))
        inv    = _get_player_pack_inventory(player) if player else []
        qty    = sum(1 for item in inv if isinstance(item, dict) and item.get("key") == key)
        await self._do_open(interaction, qty)

    @discord.ui.button(label="🔢 Open Qty", style=discord.ButtonStyle.secondary, row=1)
    async def open_qty_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(OpenQtyModal(self))

    # ── Animation ─────────────────────────────────────────────────

    async def _animate(self, msg: discord.Message, title: str, rolls: list[dict], data: dict) -> None:
        await animate_pack_open(msg, title, rolls, data, self._anim_view)

    async def _do_open(self, interaction: discord.Interaction, qty: int) -> None:
        data  = self.cog.bot.storage.load()
        key   = self._current_key(data)
        if not key:
            await error_reply(interaction, "No packs to open.")
            return

        player    = get_player(data, str(interaction.user.id))
        inv       = _get_player_pack_inventory(player) if player else []
        available = sum(1 for item in inv if isinstance(item, dict) and item.get("key") == key)
        qty       = min(qty, available)
        if qty < 1:
            await interaction.response.send_message("Not enough packs.", ephemeral=True)
            return

        pack_name = next((str(i.get("name", key)) for i in inv
                          if isinstance(i, dict) and i.get("key") == key), key)
        title = f"Opening {qty}x {pack_name}..."

        anim_view    = _AnimView(self)
        self._anim_view = anim_view
        self.skipped = False
        try:
            await interaction.response.edit_message(
                embed=_anim_embed(title, "⬛  ⬛  ⬛  ⬛  ⬛", "The pack is sealed..."),
                view=anim_view,
            )
        except TypeError:
            logger.exception(
                "[PACKS_EDIT_MSG] TypeError editing message. interaction.response=%r edit_message=%r type=%r",
                interaction.response,
                getattr(interaction.response, "edit_message", None),
                type(getattr(interaction.response, "edit_message", None)),
            )
            raise
        except Exception:
            logger.exception("[PACKS_EDIT_MSG] Unexpected error editing message")
            raise

        user_id = str(interaction.user.id)

        def mutate(d: dict[str, Any]) -> list[dict[str, str]]:
            rolls: list[dict[str, str]] = []
            for _ in range(qty):
                ok, _, r = _open_pack_from_inventory(d, user_id, key)
                if ok:
                    rolls.extend(r)
                    player = d.get("players", {}).get(user_id, {})
                    user = player.get("user", {})
                    if isinstance(user, dict):
                        advance_tutorial(user, "open_pack")
            return rolls

        all_rolls = self.cog.bot.storage.with_lock(mutate)

        if not all_rolls:
            if interaction.message:
                try:
                    await interaction.message.edit(embed=make_embed(None, "❌ Open Failed", "Could not open packs."), view=self)
                except (discord.NotFound, discord.Forbidden):
                    pass
                except discord.HTTPException:
                    logger.warning("Failed to show open-failed message", exc_info=True)
            return

        if interaction.message and not self.skipped:
            await self._animate(interaction.message, title, all_rolls, data)

        await asyncio.sleep(0.3)

        # Refresh slot state
        data2 = self.cog.bot.storage.load()
        keys2 = self._pack_keys(data2)
        self.current_slot = max(0, min(self.current_slot, len(keys2) - 1)) if keys2 else 0

        # Switch to post-reveal view
        reveal_view = PostRevealView(self.cog, interaction.user.id, all_rolls, pack_name, self)
        reveal_view.message = interaction.message
        first_embed = _card_reveal_embed(all_rolls[0], 1, len(all_rolls), pack_name)

        if interaction.message:
            try:
                await interaction.message.edit(embed=first_embed, view=reveal_view)
            except (discord.NotFound, discord.Forbidden):
                pass  # message gone or no access
            except discord.HTTPException:
                logger.warning("Failed to switch to reveal view", exc_info=True)


# ── Cog ───────────────────────────────────────────────────────────

class PacksPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="packs", description="Open your pack inventory.")
    async def packs(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data   = self.bot.storage.load()
        uid    = str(interaction.user.id)
        player = get_player(data, uid)
        inv    = _get_player_pack_inventory(player) if player else []
        panel  = PacksPanel(self, interaction.user.id)
        embed  = _panel_embed(uid, 0, inv, player)
        await interaction.followup.send(embed=embed, view=panel)
        panel.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PacksPanelCog(bot))
