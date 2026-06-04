"""Squad panel for LOOKISM HXCC — full interactive management."""

from __future__ import annotations

import math
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.cards_logic import compute_power, compute_scaled_stats, rarity_rank
from bot.utils.checks import ensure_registered
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.utils.squad_logic import compute_squad_power, get_inventory, get_player, get_squad
from bot.utils.ui import e, make_embed

BASE_HP   = 100
NUM_SLOTS = 4


# ── helpers ───────────────────────────────────────────────────────────────────

def _rarity_icon(rarity: str, data: dict | None = None) -> str:
    rmap = {"common": e("common",data), "rare": e("rare",data), "epic": e("epic",data), "legendary": e("legendary",data),
            "mythical": e("mythical",data), "abyssal": e("abyssal",data), "infernal": e("infernal",data)}
    return rmap.get(str(rarity).lower(), e("common",data))

def _star_string(stars: int) -> str:
    stars = max(0, min(5, int(stars or 0)))
    return "★" * stars + "☆" * (5 - stars)

def _slot_label(index: int) -> str:
    return f"Slot {index + 1}"

def _slot_map(index: int) -> tuple[str, int]:
    return ("active", index) if index <= 1 else ("backup", index - 2)

def _get_slot_uid(squad: dict[str, Any], index: int) -> str:
    key, idx = _slot_map(index)
    vals = squad.get(key, [])
    return str(vals[idx]) if isinstance(vals, list) and idx < len(vals) else ""

def _set_slot_uid(squad: dict[str, Any], index: int, uid: str) -> None:
    key, idx = _slot_map(index)
    vals = squad.setdefault(key, [])
    if not isinstance(vals, list):
        vals = []
        squad[key] = vals
    while len(vals) <= idx:
        vals.append("")
    vals[idx] = uid

def _cleanup_slots(squad: dict[str, Any]) -> None:
    for key in ("active", "backup"):
        vals = squad.get(key, [])
        squad[key] = [str(v) for v in vals if isinstance(vals, list) and str(v)] if isinstance(vals, list) else []

def _instance_hp(data: dict[str, Any], instance: dict[str, Any]) -> tuple[int, int]:
    card_def = (data.get("cards") or {}).get(str(instance.get("card_name", "")), {})
    scaled   = compute_scaled_stats(card_def if isinstance(card_def, dict) else {}, int(instance.get("stars", 0)))
    max_hp   = max(BASE_HP, math.floor(compute_power(scaled) / 5) + BASE_HP)
    return max(0, min(int(instance.get("hp", max_hp)), max_hp)), max_hp

def _resolve_field(raw: Any, desc_raw: Any = None) -> tuple[str, str]:
    if isinstance(raw, dict):
        return (str(raw.get("name", raw.get("title", "—"))).strip() or "—",
                str(raw.get("description", raw.get("desc", ""))).strip() or "—")
    return str(raw or "").strip() or "—", str(desc_raw or "").strip() or "—"


# ── embed builders ────────────────────────────────────────────────────────────

def _build_slot_block(data: dict[str, Any], slot_index: int, instance: dict[str, Any] | None) -> str:
    label = _slot_label(slot_index)
    if instance is None:
        return f"╭─ {label}\n│ [Empty]\n╰────────────────"

    card_name = str(instance.get("card_name", "Unknown"))
    rarity    = str(instance.get("rarity", "Common"))
    stars     = max(0, min(5, int(instance.get("stars", 0))))
    locked    = bool(instance.get("locked") or instance.get("market_locked") or instance.get("squad_locked"))

    card_def = (data.get("cards") or {}).get(card_name, {})
    scaled   = compute_scaled_stats(card_def if isinstance(card_def, dict) else {}, stars)
    power    = compute_power(scaled)

    return (
        f"╭─ {label} — {_rarity_icon(rarity)} {rarity} • {card_name}\n"
        f"│ ⚡ Power: {power:,}\n"
        f"│ ⭐ Stars: {_star_string(stars)}\n"
        f"│ 💪 STR: {int(scaled.get('strength', 0))}  ⚡ SPD: {int(scaled.get('speed', 0))}\n"
        f"│ 🛡 END: {int(scaled.get('endurance', 0))}  🎯 TEC: {int(scaled.get('technique', 0))}\n"
        f"│ 🧠 IQ: {int(scaled.get('iq', 0))}   🔮 BIQ: {int(scaled.get('battle_iq', 0))}\n"
        f"│ {'🔒 Status: Locked' if locked else '🔓 Status: Unlocked'}\n"
        "╰────────────────"
    )


def _build_squad_embed(
    data: dict[str, Any],
    user: discord.User | discord.Member,
    player: dict[str, Any],
    current_slot: int,
) -> discord.Embed:
    squad     = get_squad(player)
    inventory = {str(i.get("uid", "")): i for i in get_inventory(player) if isinstance(i, dict)}
    total_power = compute_squad_power(data, player)
    filled = sum(1 for i in range(NUM_SLOTS) if _get_slot_uid(squad, i))

    overview = (
        "╭─ Squad Overview\n"
        f"│ ⚡ Total Power: {total_power:,}\n"
        f"│ 👥 Slots Filled: {filled}/{NUM_SLOTS}\n"
        "╰────────────────"
    )

    blocks: list[str] = []
    for i in range(NUM_SLOTS):
        uid  = _get_slot_uid(squad, i)
        inst = inventory.get(uid) if uid else None
        block = _build_slot_block(data, i, inst)
        # highlight the currently focused slot
        if i == current_slot:
            block = f"**{block}**" if inst is None else block.replace("╭─", "╭─ 👉", 1)
        blocks.append(block)

    body = overview + "\n\n" + "\n\n".join(blocks)

    embed = make_embed(None, "LOOKISM HXCC • SQUAD", body, color=0xE11D48, footer=f"Viewing {_slot_label(current_slot)} • Squad Management", thumbnail_url=user.display_avatar.url)
    return embed


def _build_fighter_embed(data: dict[str, Any], instance: dict[str, Any]) -> discord.Embed:
    """Full fighter detail — same layout as collection_view."""
    card_name = str(instance.get("card_name", "Unknown"))
    rarity    = str(instance.get("rarity", "Common"))
    stars     = max(0, min(5, int(instance.get("stars", 0))))
    locked    = bool(instance.get("locked") or instance.get("market_locked") or instance.get("squad_locked"))

    card_def  = (data.get("cards") or {}).get(card_name, {})
    scaled    = compute_scaled_stats(card_def if isinstance(card_def, dict) else {}, stars)
    power     = compute_power(scaled)
    image_url = str(card_def.get("image_url", "")).strip() if isinstance(card_def, dict) else ""

    mastery_raw  = card_def.get("mastery", []) if isinstance(card_def, dict) else []
    mastery_list = [str(m).strip().title() for m in mastery_raw if str(m).strip()] if isinstance(mastery_raw, list) else []
    mastery_str  = "  ".join(f"• {m}" for m in mastery_list) if mastery_list else "—"

    unique_path,  unique_path_desc  = _resolve_field(card_def.get("unique_path") if isinstance(card_def, dict) else None,
                                                      card_def.get("unique_path_description") if isinstance(card_def, dict) else None)
    unique_skill, unique_skill_desc = _resolve_field(card_def.get("unique_skill") if isinstance(card_def, dict) else None,
                                                      card_def.get("unique_skill_description") if isinstance(card_def, dict) else None)

    body = (
        f"{_rarity_icon(rarity)} {rarity} • {card_name}\n\n"
        "╭─ Combat Stats\n"
        f"│ 💪 STR: {int(scaled.get('strength', 0))}\n"
        f"│ ⚡ SPD: {int(scaled.get('speed', 0))}\n"
        f"│ 🛡 END: {int(scaled.get('endurance', 0))}\n"
        f"│ 🎯 TEC: {int(scaled.get('technique', 0))}\n"
        f"│ 🧠 IQ: {int(scaled.get('iq', 0))}\n"
        f"│ 🔮 BIQ: {int(scaled.get('battle_iq', 0))}\n"
        "╰────────────────\n\n"
        "╭─ Progression\n"
        f"│ ⭐ Stars: {_star_string(stars)}\n"
        f"│ ⚡ Power: {power:,}\n"
        f"│ {'🔒 Status: Locked' if locked else '🔓 Status: Unlocked'}\n"
        "╰────────────────\n\n"
        "╭─ Mastery\n"
        f"│ {mastery_str}\n"
        "╰────────────────\n\n"
        "╭─ Unique Path\n"
        f"│ {unique_path}\n"
        f"│ {unique_path_desc}\n"
        "╰────────────────\n\n"
        "╭─ Unique Skill\n"
        f"│ {unique_skill}\n"
        f"│ {unique_skill_desc}\n"
        "╰────────────────"
    )
    embed = make_embed(None, "LOOKISM HXCC • FIGHTER", body, color=0xE11D48, image_url=image_url, footer="Squad • Fighter Detail")
    return embed


# ── sub-views ─────────────────────────────────────────────────────────────────

class AssignSelect(discord.ui.Select):
    def __init__(self, cog: "SquadCog", panel: "SquadPanel", options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="🎴 Choose a card to assign…", min_values=1, max_values=1,
                         options=options, row=0)
        self.cog   = cog
        self.panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        uid = self.values[0]
        status, card_name, power = self.cog._assign_uid_to_slot(
            str(interaction.user.id), self.panel.current_slot, uid
        )
        data = self.cog.bot.storage.load()
        if status != "ok":
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Assignment Failed", "Could not assign that card to this slot."),
                ephemeral=True,
            )
            return
        # Reload player and return to main panel
        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.panel.current_slot)
        await interaction.response.edit_message(embed=embed, view=self.panel)
        self.panel.message = interaction.message


class SwapSelect(discord.ui.Select):
    def __init__(self, cog: "SquadCog", panel: "SquadPanel", first_slot: int | None = None) -> None:
        options = [discord.SelectOption(label=_slot_label(i), value=str(i)) for i in range(NUM_SLOTS)]
        ph = "🔁 Swap with which slot?" if first_slot is not None else "🔁 First slot to swap…"
        super().__init__(placeholder=ph, min_values=1, max_values=1, options=options, row=0)
        self.cog        = cog
        self.panel      = panel
        self.first_slot = first_slot

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = int(self.values[0])
        data = self.cog.bot.storage.load()

        if self.first_slot is None:
            # Step 2: pick second slot
            view = _SubView(self.panel.invoker_id)
            view.add_item(SwapSelect(self.cog, self.panel, first_slot=selected))
            await interaction.response.edit_message(
                embed=make_embed(data, "🔄 Swap — Step 2",
                                 f"First: **{_slot_label(selected)}** — now pick the second slot."),
                view=view,
            )
            return

        if selected == self.first_slot:
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Invalid Swap", "Pick a **different** slot."),
                ephemeral=True,
            )
            return

        status, power = self.cog._swap_slots(str(interaction.user.id), self.first_slot, selected)
        if status != "ok":
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Swap Failed", "Could not swap those slots."),
                ephemeral=True,
            )
            return

        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.panel.current_slot)
        await interaction.response.edit_message(embed=embed, view=self.panel)
        self.panel.message = interaction.message


class ClearConfirmView(discord.ui.View):
    def __init__(self, cog: "SquadCog", panel: "SquadPanel") -> None:
        super().__init__(timeout=30)
        self.cog   = cog
        self.panel = panel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.panel.invoker_id:
            await error_reply(interaction, "Not your panel.")
            return False
        return True

    @discord.ui.button(label="✅ Confirm Clear All", style=discord.ButtonStyle.danger, row=0)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        status = self.cog._clear_squad(str(interaction.user.id))
        data   = self.cog.bot.storage.load()
        if status != "ok":
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Failed", "Could not clear squad."),
                ephemeral=True,
            )
            return
        player = get_player(data, str(interaction.user.id))
        self.panel.current_slot = 0
        embed = _build_squad_embed(data, interaction.user, player, 0)
        await interaction.response.edit_message(embed=embed, view=self.panel)
        self.panel.message = interaction.message

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data   = self.cog.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.panel.current_slot)
        await interaction.response.edit_message(embed=embed, view=self.panel)
        self.panel.message = interaction.message


class _SubView(discord.ui.View):
    def __init__(self, invoker_id: int) -> None:
        super().__init__(timeout=60)
        self.invoker_id = invoker_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await error_reply(interaction, "Not your panel.")
            return False
        return True


# ── main panel ────────────────────────────────────────────────────────────────

class SquadPanel(discord.ui.View):
    def __init__(self, cog: "SquadCog", invoker_id: int) -> None:
        super().__init__(timeout=180)
        self.cog          = cog
        self.invoker_id   = invoker_id
        self.current_slot = 0
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This squad panel belongs to another player.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    # ── Row 0: Navigation ──────────────────────────────────────────────────

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_slot(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.current_slot = (self.current_slot - 1) % NUM_SLOTS
        data   = self.cog.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.current_slot)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_slot(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.current_slot = (self.current_slot + 1) % NUM_SLOTS
        data   = self.cog.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.current_slot)
        await interaction.response.edit_message(embed=embed, view=self)

    # ── Row 1: Slot Actions ────────────────────────────────────────────────

    @discord.ui.button(label="📥 Assign", style=discord.ButtonStyle.success, row=1)
    async def assign_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        options = self.cog._inventory_options(str(interaction.user.id), self.current_slot)
        data    = self.cog.bot.storage.load()
        if not options:
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} No Cards", "No unassigned cards available for this slot."),
                ephemeral=True,
            )
            return
        view = _SubView(self.invoker_id)
        view.add_item(AssignSelect(self.cog, self, options))
        await interaction.response.edit_message(
            embed=make_embed(data, f"📥 Assign — {_slot_label(self.current_slot)}",
                             "Choose a card from your inventory to assign to this slot."),
            view=view,
        )

    @discord.ui.button(label="📤 Remove", style=discord.ButtonStyle.danger, row=1)
    async def remove_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        status, removed_name, power = self.cog._remove_slot(str(interaction.user.id), self.current_slot)
        data = self.cog.bot.storage.load()
        if status != "ok":
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Slot Empty",
                                 f"{_slot_label(self.current_slot)} has no card assigned."),
                ephemeral=True,
            )
            return
        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.current_slot)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔄 Swap", style=discord.ButtonStyle.secondary, row=1)
    async def swap_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        view = _SubView(self.invoker_id)
        view.add_item(SwapSelect(self.cog, self))
        await interaction.response.edit_message(
            embed=make_embed(data, "🔄 Swap Slots — Step 1", "Pick the first slot you want to swap."),
            view=view,
        )

    # ── Row 2: Extras ──────────────────────────────────────────────────────

    @discord.ui.button(label="👁 View", style=discord.ButtonStyle.secondary, row=2)
    async def view_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data   = self.cog.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        squad  = get_squad(player)
        uid    = _get_slot_uid(squad, self.current_slot)
        if not uid:
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Empty Slot",
                                 f"{_slot_label(self.current_slot)} has no card assigned."),
                ephemeral=True,
            )
            return
        inventory = {str(i.get("uid", "")): i for i in get_inventory(player) if isinstance(i, dict)}
        inst = inventory.get(uid)
        if not inst:
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Card Missing", "Card data not found."),
                ephemeral=True,
            )
            return
        # Show full fighter detail; back button returns to squad panel
        back_view = _BackView(self.invoker_id, self, data, interaction.user, player)
        await interaction.response.edit_message(embed=_build_fighter_embed(data, inst), view=back_view)

    @discord.ui.button(label="🗑 Clear All", style=discord.ButtonStyle.danger, row=2)
    async def clear_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data = self.cog.bot.storage.load()
        await interaction.response.edit_message(
            embed=make_embed(data, "🗑 Clear All Slots",
                             "This will remove **all cards** from your squad.\nAre you sure?"),
            view=ClearConfirmView(self.cog, self),
        )


class _BackView(discord.ui.View):
    """Minimal view shown on fighter detail — just a Back button."""
    def __init__(self, invoker_id: int, panel: SquadPanel,
                 data: dict[str, Any], user: discord.User | discord.Member,
                 player: dict[str, Any]) -> None:
        super().__init__(timeout=60)
        self.invoker_id = invoker_id
        self.panel      = panel
        self.data       = data
        self.user       = user
        self.player     = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await error_reply(interaction, "Not your panel.")
            return False
        return True

    @discord.ui.button(label="← Back to Squad", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        data   = self.panel.cog.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        embed  = _build_squad_embed(data, interaction.user, player, self.panel.current_slot)
        await interaction.response.edit_message(embed=embed, view=self.panel)
        self.panel.message = interaction.message


# ── cog ───────────────────────────────────────────────────────────────────────

class SquadCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── logic helpers ──────────────────────────────────────────────────────

    def _inventory_options(self, user_id: str, slot_index: int) -> list[discord.SelectOption]:
        data      = self.bot.storage.load()
        player    = get_player(data, user_id)
        if player is None:
            return []
        inventory = get_inventory(player)
        squad     = get_squad(player)
        current   = _get_slot_uid(squad, slot_index)
        assigned  = {str(u) for u in squad.get("active", []) + squad.get("backup", []) if str(u)}
        if current:
            assigned.discard(current)

        options: list[discord.SelectOption] = []
        for item in sorted(inventory, key=lambda x: (-rarity_rank(str(x.get("rarity", "Common"))), -int(x.get("stars", 0)))):
            uid = str(item.get("uid", ""))
            if not uid or uid in assigned:
                continue
            rarity = str(item.get("rarity", "Common"))
            stars  = int(item.get("stars", 0))
            label  = f"{_rarity_icon(rarity)} {item.get('card_name', 'Unknown')} {_star_string(stars)}"[:100]
            desc   = f"{rarity} • UID: {uid[:8]}"[:100]
            options.append(discord.SelectOption(label=label, value=uid, description=desc))
            if len(options) >= 25:
                break
        return options

    def _assign_uid_to_slot(self, user_id: str, slot_index: int, uid: str) -> tuple[str, str, int]:
        def mutate(data: dict[str, Any]) -> tuple[str, str, int]:
            player    = get_player(data, user_id)
            if player is None:
                return "not_registered", "", 0
            squad     = get_squad(player)
            inventory = get_inventory(player)
            inst      = next((i for i in inventory if str(i.get("uid", "")) == uid), None)
            if not isinstance(inst, dict):
                return "not_found", "", compute_squad_power(data, player)
            old_uid = _get_slot_uid(squad, slot_index)
            for key in ("active", "backup"):
                vals = squad.get(key, [])
                if isinstance(vals, list):
                    squad[key] = [str(v) for v in vals if str(v) != uid]
            _set_slot_uid(squad, slot_index, uid)
            _cleanup_slots(squad)
            all_assigned = set(squad.get("active", []) + squad.get("backup", []))
            for item in inventory:
                iuid = str(item.get("uid", ""))
                if iuid == uid:
                    item["squad_locked"] = True
                elif iuid == old_uid:
                    item["squad_locked"] = iuid in all_assigned
            return "ok", str(inst.get("card_name", "Unknown")), compute_squad_power(data, player)
        return self.bot.storage.with_lock(mutate)

    def _remove_slot(self, user_id: str, slot_index: int) -> tuple[str, str, int]:
        def mutate(data: dict[str, Any]) -> tuple[str, str, int]:
            player    = get_player(data, user_id)
            if player is None:
                return "not_registered", "", 0
            squad     = get_squad(player)
            inventory = get_inventory(player)
            uid       = _get_slot_uid(squad, slot_index)
            if not uid:
                return "empty", "", compute_squad_power(data, player)
            _set_slot_uid(squad, slot_index, "")
            _cleanup_slots(squad)
            removed_name = "Card"
            still_in = uid in set(squad.get("active", []) + squad.get("backup", []))
            for item in inventory:
                if str(item.get("uid", "")) == uid:
                    removed_name = str(item.get("card_name", "Card"))
                    item["squad_locked"] = still_in
                    break
            return "ok", removed_name, compute_squad_power(data, player)
        return self.bot.storage.with_lock(mutate)

    def _swap_slots(self, user_id: str, a: int, b: int) -> tuple[str, int]:
        def mutate(data: dict[str, Any]) -> tuple[str, int]:
            player = get_player(data, user_id)
            if player is None:
                return "not_registered", 0
            squad = get_squad(player)
            ua = _get_slot_uid(squad, a)
            ub = _get_slot_uid(squad, b)
            _set_slot_uid(squad, a, ub)
            _set_slot_uid(squad, b, ua)
            _cleanup_slots(squad)
            return "ok", compute_squad_power(data, player)
        return self.bot.storage.with_lock(mutate)

    def _clear_squad(self, user_id: str) -> str:
        def mutate(data: dict[str, Any]) -> str:
            player = get_player(data, user_id)
            if player is None:
                return "not_registered"
            squad = get_squad(player)
            inv   = get_inventory(player)
            to_unlock = {str(u) for u in squad.get("active", []) + squad.get("backup", []) if str(u)}
            squad["active"]  = []
            squad["backup"]  = []
            for item in inv:
                if str(item.get("uid", "")) in to_unlock:
                    item["squad_locked"] = False
            return "ok"
        return self.bot.storage.with_lock(mutate)

    # ── command ────────────────────────────────────────────────────────────

    @app_commands.command(name="squad", description="Open your squad management panel.")
    async def squad(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return

        data   = self.bot.storage.load()
        player = get_player(data, str(interaction.user.id))
        if player is None:
            await interaction.response.send_message(
                embed=make_embed(data, f"{e('warning', data)} Not Registered",
                                 "Run `/start` to create your account first."),
                ephemeral=True,
            )
            return

        panel = SquadPanel(self, interaction.user.id)
        embed = _build_squad_embed(data, interaction.user, player, 0)
        await interaction.response.send_message(embed=embed, view=panel)
        panel.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SquadCog(bot))
