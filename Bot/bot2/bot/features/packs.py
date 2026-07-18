"""Pack commands: player buy + owner interactive management panel."""

from __future__ import annotations

import logging
import random
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import OWNER_GUILD_ID
from bot.utils.cards_logic import build_card_instance
from bot.utils.checks import ensure_registered, is_owner
from bot.utils.timeutil import now_ts as _now_ts
from bot.utils.pack_logic import ensure_packs_structure, format_rates_table, get_pack_by_name, normalize_pack_key
from bot.utils.timeutil import now_ts
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply

logger = logging.getLogger(__name__)

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


def _get_player_pack_inventory(player: dict[str, Any]) -> list[dict[str, Any]]:
    """Get the player's stored (unopened) pack inventory."""
    user = player.get("user", {}) if isinstance(player, dict) else {}
    inv = user.get("pack_inventory", []) if isinstance(user, dict) else []
    return inv if isinstance(inv, list) else []


def _add_packs_to_inventory(data: dict[str, Any], user_id: str, pack_key: str, qty: int) -> None:
    """Store qty packs in player's pack_inventory without opening."""
    player = data.get("players", {}).get(user_id)
    if not isinstance(player, dict):
        return
    user = player.get("user", {})
    if not isinstance(user, dict):
        return
    pack_inv = user.setdefault("pack_inventory", [])
    if not isinstance(pack_inv, list):
        pack_inv = []
        user["pack_inventory"] = pack_inv
    ensure_packs_structure(data)
    pack_defs = data.get("packs", {}).get("definitions", {})
    pack_def = pack_defs.get(pack_key, {})
    pack_name = str(pack_def.get("name", pack_key)) if isinstance(pack_def, dict) else pack_key
    now = int(_now_ts())
    for _ in range(qty):
        pack_inv.append({"key": pack_key, "name": pack_name, "acquired_at": now})


def _remove_pack_from_inventory(data: dict[str, Any], user_id: str, pack_key: str, qty: int = 1) -> bool:
    """Remove qty packs from pack_inventory. Returns True if successful."""
    player = data.get("players", {}).get(user_id)
    if not isinstance(player, dict):
        return False
    user = player.get("user", {})
    pack_inv = user.get("pack_inventory", []) if isinstance(user, dict) else []
    if not isinstance(pack_inv, list):
        return False
    removed = 0
    new_inv = []
    for item in pack_inv:
        if isinstance(item, dict) and item.get("key") == pack_key and removed < qty:
            removed += 1
        else:
            new_inv.append(item)
    if removed < qty:
        return False
    user["pack_inventory"] = new_inv
    return True


def _open_pack_from_inventory(data: dict[str, Any], user_id: str, pack_key: str) -> tuple[bool, str, list[dict[str, str]]]:
    """Open one stored pack. Returns (ok, reason, rolls)."""
    import random as _random

    player = data.get("players", {}).get(user_id)
    if not isinstance(player, dict):
        return False, "not_registered", []
    user = player.get("user", {})
    if not isinstance(user, dict):
        return False, "no_user", []

    ensure_packs_structure(data)
    pack_defs = data.get("packs", {}).get("definitions", {})
    pack_def = pack_defs.get(pack_key)
    if not isinstance(pack_def, dict):
        from bot.data.defaults import DEFAULT_PACK_DEFINITIONS
        pack_def = DEFAULT_PACK_DEFINITIONS.get(pack_key, {})
    if not pack_def:
        return False, "pack_not_found", []

    catalog = _get_catalog(data)
    rates = _pack_rates(pack_def)
    available = _available_rates(rates, catalog)
    if not available:
        return False, "no_eligible_cards", []

    if not _remove_pack_from_inventory(data, user_id, pack_key, 1):
        return False, "no_packs", []

    inventory = user.get("inventory", [])
    if not isinstance(inventory, list):
        inventory = []

    rolls: list[dict[str, str]] = []
    now = int(_now_ts())
    cards_per = int(pack_def.get("cards_per_pack", 1))
    for _ in range(cards_per):
        rarity = _weighted_pick(available)
        if not rarity:
            continue
        pool = _eligible_pool_for_rarity(catalog, rarity)
        if not pool:
            continue
        card_name, card_def = _random.choice(pool)
        instance = build_card_instance(card_def, acquired_at=now, stars=0)
        inventory.append(instance)
        rolls.append({
            "uid": str(instance.get("uid", "")),
            "name": card_name,
            "rarity": str(card_def.get("rarity", rarity)),
            "image_url": str(card_def.get("image_url", "")).strip(),
        })

    user["inventory"] = inventory
    return True, "ok", rolls


def _get_catalog(data: dict[str, Any]) -> dict[str, Any]:
    cards = data.get("cards")
    if isinstance(cards, dict):
        return cards
    catalog = data.get("catalog")
    return catalog if isinstance(catalog, dict) else {}


def _norm_rarity(s: str) -> str:
    return str(s or "").strip().lower()


def _norm_pack_name(s: str) -> str:
    return normalize_pack_key(str(s or "").strip())


def _title_rarity(s: str) -> str:
    raw = str(s or "").strip()
    return raw[:1].upper() + raw[1:].lower() if raw else ""


def _packs_root(data: dict[str, Any]) -> dict[str, Any]:
    ensure_packs_structure(data)
    packs = data.get("packs", {})
    if not isinstance(packs, dict):
        data["packs"] = {"definitions": {}, "stats": {"total_packs_opened": 0, "total_spent": 0}}
    root = data["packs"].get("definitions", {})
    if not isinstance(root, dict):
        data["packs"]["definitions"] = {}
    return data["packs"]["definitions"]


def _get_pack(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    key, pack = get_pack_by_name(data, name)
    if key and isinstance(pack, dict):
        return pack
    return None


def _pack_price(pack: dict[str, Any]) -> int:
    return int(pack.get("price", 0)) if isinstance(pack, dict) else 0


def _pack_rates(pack: dict[str, Any]) -> dict[str, float]:
    rates = pack.get("rates", {}) if isinstance(pack, dict) else {}
    return rates if isinstance(rates, dict) else {}


def _set_pack_price(pack: dict[str, Any], price: int) -> None:
    if isinstance(pack, dict):
        pack["price"] = int(max(0, price))


def _card_is_eligible(card_name: str, card: dict[str, Any], chosen_rarity: str) -> tuple[bool, str]:
    if not card_name:
        return False, "missing_name"
    if _norm_rarity(card.get("rarity", "")) != _norm_rarity(chosen_rarity):
        return False, "mismatch"
    has_stats = isinstance(card.get("stats"), dict)
    has_power = card.get("power") is not None
    if not (has_stats or has_power):
        return False, "missing_min_fields"
    return True, "ok"


def _weighted_pick(rates: dict[str, Any]) -> str:
    weighted: list[str] = []
    for rarity, w in rates.items():
        try:
            weight = int(float(w))
        except Exception:
            weight = 0
        if weight > 0:
            weighted.extend([str(rarity)] * weight)
    return random.choice(weighted) if weighted else ""


def _wallet_balance(user: dict[str, Any]) -> int:
    """Read balance. Single source of truth is ``balance``.

    Legacy ``coins`` field (from v1 migration) is ignored for reads
    to prevent exploit via desync, but cleaned up on writes.
    """
    if not isinstance(user, dict):
        return 0
    return int(user.get("balance", 0) or 0)


def _set_wallet_balance(user: dict[str, Any], value: int) -> int:
    """Write balance and clean up legacy ``coins`` mirror."""
    new_value = int(max(0, value))
    user["balance"] = new_value
    # Clean up legacy field to prevent drift exploits
    user.pop("coins", None)
    return new_value


def _eligible_pool_for_rarity(catalog: dict[str, Any], chosen_rarity: str) -> list[tuple[str, dict[str, Any]]]:
    pool: list[tuple[str, dict[str, Any]]] = []
    for cname, cdef in catalog.items():
        if not isinstance(cdef, dict):
            continue
        ok, _why = _card_is_eligible(str(cname), cdef, chosen_rarity)
        if ok:
            pool.append((str(cname), cdef))
    return pool


def _available_rates(rates: dict[str, Any], catalog: dict[str, Any]) -> dict[str, int]:
    """Return only weighted rarities that actually have at least one eligible card."""
    out: dict[str, int] = {}
    for rarity, raw_weight in rates.items():
        try:
            weight = int(float(raw_weight))
        except Exception:
            weight = 0
        if weight <= 0:
            continue
        if _eligible_pool_for_rarity(catalog, str(rarity)):
            out[str(rarity)] = weight
    return out


class CreatePackModal(discord.ui.Modal, title="Create Pack"):
    pack_name = discord.ui.TextInput(label="Pack Name", required=True, max_length=64)
    initial_price = discord.ui.TextInput(label="Initial Price", required=False, default="0", max_length=16)

    def __init__(self, view: "PackPanelView") -> None:
        super().__init__(timeout=120)
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view_ref.create_name = str(self.pack_name.value).strip()
        self.view_ref.pending_value = str(self.initial_price.value).strip() or "0"
        self.view_ref.selected_action = "create_pack"
        await self.view_ref._commit(interaction)


class ValueModal(discord.ui.Modal, title="Set Value"):
    value = discord.ui.TextInput(label="Value", required=True, max_length=32)

    def __init__(self, view: "PackPanelView", title: str, seed: str = "") -> None:
        super().__init__(timeout=120, title=title)
        self.view_ref = view
        self.value.default = seed

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view_ref.pending_value = str(self.value.value).strip()
        await self.view_ref._refresh(interaction, "Value captured. Press Apply.")


class CustomRarityModal(discord.ui.Modal, title="Custom Rarity"):
    rarity = discord.ui.TextInput(label="Rarity Name", required=True, max_length=32)

    def __init__(self, view: "PackPanelView") -> None:
        super().__init__(timeout=120)
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view_ref.selected_rarity = _title_rarity(str(self.rarity.value))
        await self.view_ref._refresh(interaction, f"Rarity set to {self.view_ref.selected_rarity}.")


class PackSelect(discord.ui.Select):
    def __init__(self, view: "PackPanelView", options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select or create pack", min_values=1, max_values=1, options=options, row=0)
        self.panel = view

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "__create__":
            await interaction.response.send_modal(CreatePackModal(self.panel))
            return
        self.panel.selected_pack = val
        self.panel.selected_rarity = ""
        self.panel.pending_value = ""
        await self.panel._refresh(interaction, f"Selected pack: {val}")


class ActionSelect(discord.ui.Select):
    def __init__(self, view: "PackPanelView") -> None:
        opts = [
            discord.SelectOption(label="📋 View", value="view"),
            discord.SelectOption(label="💰 Set Price", value="set_price"),
            discord.SelectOption(label="🎯 Set/Update Rate", value="set_rate"),
            discord.SelectOption(label="🧹 Delete Rate", value="delete_rate"),
            discord.SelectOption(label="♻ Reset Rates", value="reset_rates"),
            discord.SelectOption(label="🗑 Delete Pack", value="delete_pack"),
        ]
        super().__init__(placeholder="Choose action", min_values=1, max_values=1, options=opts, row=1)
        self.panel = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.selected_action = self.values[0]
        self.panel.pending_value = ""
        await self.panel._refresh(interaction, f"Action: {self.panel.selected_action}")


class RaritySelect(discord.ui.Select):
    def __init__(self, view: "PackPanelView", options: list[discord.SelectOption], disabled: bool) -> None:
        super().__init__(placeholder="Select rarity", min_values=1, max_values=1, options=options, disabled=disabled, row=2)
        self.panel = view

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "__custom__":
            await interaction.response.send_modal(CustomRarityModal(self.panel))
            return
        self.panel.selected_rarity = val
        await self.panel._refresh(interaction, f"Rarity: {val}")


class PackPanelView(discord.ui.View):
    def __init__(self, cog: "PacksCog", owner_id: str) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.selected_pack: str | None = None
        self.selected_action = "view"
        self.selected_rarity = ""
        self.pending_value = ""
        self.confirm_mode = ""
        self.pack_page = 0
        self.create_name = ""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id:
            await smart_reply(interaction, "Not your panel.", ephemeral=True)
            return False
        if not is_owner(interaction):
            await smart_reply(interaction, "Owner only.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

    def _pack_names(self, data: dict[str, Any]) -> list[str]:
        names = []
        for key, pack in _packs_root(data).items():
            if isinstance(pack, dict):
                names.append(str(pack.get("name", key)))
        return sorted(names, key=lambda x: x.lower())

    def _rebuild(self, data: dict[str, Any]) -> None:
        self.clear_items()
        names = self._pack_names(data)
        total_pages = max(1, (len(names) + 23) // 24)
        self.pack_page = max(0, min(self.pack_page, total_pages - 1))
        start = self.pack_page * 24
        show = names[start : start + 24]

        pack_opts = [discord.SelectOption(label="➕ Create New Pack", value="__create__")]
        for n in show:
            pack_opts.append(discord.SelectOption(label=n[:100] or "Pack", value=n or "pack"))
        self.add_item(PackSelect(self, pack_opts[:25]))
        self.add_item(ActionSelect(self))

        rates = _pack_rates(_get_pack(data, self.selected_pack or "") or {})
        rarity_opts = [discord.SelectOption(label="➕ Custom...", value="__custom__")]
        for r in sorted(rates.keys()):
            rarity_opts.append(discord.SelectOption(label=str(r)[:100] or "Rarity", value=str(r) or "rarity"))
        rarity_disabled = self.selected_action not in {"set_rate", "delete_rate"}
        self.add_item(RaritySelect(self, rarity_opts[:25], rarity_disabled))

        prev_btn = discord.ui.Button(label="Prev Packs", style=discord.ButtonStyle.secondary, row=3, disabled=self.pack_page <= 0)
        next_btn = discord.ui.Button(label="Next Packs", style=discord.ButtonStyle.secondary, row=3, disabled=self.pack_page >= total_pages - 1)
        enter_btn = discord.ui.Button(label="✍ Enter Value", style=discord.ButtonStyle.primary, row=3)
        apply_btn = discord.ui.Button(label="✅ Apply", style=discord.ButtonStyle.success, row=4)
        confirm_btn = discord.ui.Button(label="⚠ Confirm", style=discord.ButtonStyle.danger, row=4)
        cancel_btn = discord.ui.Button(label="❌ Cancel", style=discord.ButtonStyle.secondary, row=4)
        close_btn = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, row=4)

        async def _prev(interaction: discord.Interaction) -> None:
            self.pack_page -= 1
            await self._refresh(interaction)

        async def _next(interaction: discord.Interaction) -> None:
            self.pack_page += 1
            await self._refresh(interaction)

        async def _enter(interaction: discord.Interaction) -> None:
            title = "Set Value"
            if self.selected_action == "set_price":
                title = "Set Price"
            elif self.selected_action == "set_rate":
                title = "Set Rate"
            await interaction.response.send_modal(ValueModal(self, title, self.pending_value))

        async def _apply(interaction: discord.Interaction) -> None:
            await self._commit(interaction)

        async def _confirm(interaction: discord.Interaction) -> None:
            if self.selected_action in {"reset_rates", "delete_rate", "delete_pack"} and self.confirm_mode != self.selected_action:
                self.confirm_mode = self.selected_action
                await self._refresh(interaction, f"⚠ Confirm {self.selected_action} by pressing Confirm again.")
                return
            await self._commit(interaction)

        async def _cancel(interaction: discord.Interaction) -> None:
            self.confirm_mode = ""
            self.pending_value = ""
            await self._refresh(interaction, "Cancelled.")

        async def _close(interaction: discord.Interaction) -> None:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)

        prev_btn.callback = _prev
        next_btn.callback = _next
        enter_btn.callback = _enter
        apply_btn.callback = _apply
        confirm_btn.callback = _confirm
        cancel_btn.callback = _cancel
        close_btn.callback = _close

        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(enter_btn)
        self.add_item(apply_btn)
        self.add_item(confirm_btn)
        self.add_item(cancel_btn)
        self.add_item(close_btn)

    def _embed(self, data: dict[str, Any], note: str = "") -> discord.Embed:
        pack = _get_pack(data, self.selected_pack or "") if self.selected_pack else None
        price = _pack_price(pack or {})
        rates = _pack_rates(pack or {})
        total = sum(float(v) for v in rates.values()) if rates else 0.0
        rates_lines = [f"{_title_rarity(k)}: {float(v):.2f}%" for k, v in sorted(rates.items())] or ["No rates configured."]
        warning = "\n⚠ Total not 100%." if rates and abs(total - 100.0) > 0.01 else ""
        desc = (
            "🧰 Pack Management Panel\n"
            f"Selected Pack: {self.selected_pack or 'None'}\n"
            f"Price: {price}\n"
            f"Rates:\n" + "\n".join(rates_lines) + f"\nTotal: {total:.2f}%{warning}\n\n"
            f"Action: {self.selected_action}\n"
            f"Rarity: {self.selected_rarity or '-'}\n"
            f"Pending Value: {self.pending_value or '-'}\n"
            f"Confirm: {self.confirm_mode or '-'}"
        )
        if note:
            desc += f"\n\n{note}"
        return make_embed(data, "🧰 Pack Management Panel", box("Pack Manager", [l for l in desc.splitlines() if l.strip()]))

    async def _refresh(self, interaction: discord.Interaction, note: str = "") -> None:
        data = self.cog.bot.storage.load()
        self._rebuild(data)
        embed = self._embed(data, note)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def _commit(self, interaction: discord.Interaction) -> None:
        action = self.selected_action
        selected_pack = self.selected_pack or ""
        selected_rarity = self.selected_rarity
        pending_value = self.pending_value
        confirm_mode = self.confirm_mode
        create_name = self.create_name

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            root = _packs_root(data)

            if action == "create_pack":
                name = str(create_name).strip()
                if not name:
                    return False, "Pack name required."
                key = _norm_pack_name(name)
                if key in root or any(str((p or {}).get("name", "")).lower() == name.lower() for p in root.values() if isinstance(p, dict)):
                    return False, "Pack already exists."
                try:
                    price = int(float(pending_value or 0))
                except Exception:
                    return False, "Invalid initial price."
                root[key] = {"key": key, "name": name, "price": max(0, price), "enabled": True, "rates": {}, "created_at": now_ts()}
                return True, f"Created pack {name}."

            pack = _get_pack(data, selected_pack)
            if not isinstance(pack, dict):
                return False, "Select a pack first."

            if action == "set_price":
                try:
                    val = int(float(pending_value))
                except Exception:
                    return False, "Price must be a number."
                _set_pack_price(pack, val)
                return True, f"Price set to {val}."

            if action == "set_rate":
                rarity = _title_rarity(selected_rarity)
                if not rarity:
                    return False, "Select rarity first."
                try:
                    val = float(pending_value)
                except Exception:
                    return False, "Rate must be a number."
                if val <= 0:
                    return False, "Rate must be > 0."
                rates = _pack_rates(pack)
                rates[rarity] = val
                pack["rates"] = rates
                return True, f"Rate set: {rarity}={val:.2f}%"

            if action == "delete_rate":
                if confirm_mode != "delete_rate":
                    return False, "Confirm delete_rate first."
                rarity = _title_rarity(selected_rarity)
                rates = _pack_rates(pack)
                if rarity not in rates:
                    return False, f"Rarity {rarity} not found."
                rates.pop(rarity, None)
                pack["rates"] = rates
                return True, f"Deleted rate {rarity}."

            if action == "reset_rates":
                if confirm_mode != "reset_rates":
                    return False, "Confirm reset_rates first."
                pack["rates"] = {}
                return True, "Rates reset."

            if action == "delete_pack":
                if confirm_mode != "delete_pack":
                    return False, "Confirm delete_pack first."
                key = None
                for k, p in root.items():
                    if isinstance(p, dict) and str(p.get("name", "")).lower() == selected_pack.lower():
                        key = k
                        break
                if key is None:
                    key = _norm_pack_name(selected_pack)
                if key not in root:
                    return False, "Pack not found."
                root.pop(key, None)
                return True, "Pack deleted."

            return True, "No changes."

        ok, msg = self.cog.bot.storage.with_lock(mutate)
        if ok:
            if action == "create_pack":
                self.selected_pack = create_name
                self.create_name = ""
                self.selected_action = "view"
            if action == "delete_pack":
                self.selected_pack = None
                self.selected_action = "view"
            self.confirm_mode = ""
            self.pending_value = ""
        await self._refresh(interaction, msg)


def grant_newbie_packs(data: dict[str, Any], user_id: str) -> int:
    """
    Store 3 free Newbie Packs in a newly registered player's pack_inventory.
    Returns the number of packs granted.
    """
    player = data.get("players", {}).get(user_id)
    if not isinstance(player, dict):
        return 0
    _add_packs_to_inventory(data, user_id, "newbie_pack", 3)
    return 3


class PacksCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
    async def cog_unload(self) -> None:
        pass

    @app_commands.command(name="o_pack", description="Owner: open pack management panel.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_pack(self, interaction: discord.Interaction) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return
        view = PackPanelView(self, str(interaction.user.id))
        view._rebuild(data)
        await smart_reply(interaction, embed=view._embed(data), view=view, ephemeral=True)

    async def pack_buy(self, interaction: discord.Interaction, pack_name: str, quantity: int) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return

        user_id = str(interaction.user.id)
        qty = max(1, int(quantity or 1))
        logger.info("[PACK_BUY] user=%s pack=%s qty_req=%s", user_id, pack_name, quantity)

        def mutate(data: dict[str, Any]):
            ensure_packs_structure(data)
            key, pack = get_pack_by_name(data, pack_name)
            if not key or not isinstance(pack, dict):
                return False, "pack_not_found", None
            if key == "war_pack" or not bool(pack.get("shop_visible", True)):
                return False, "pack_disabled", None
            if not bool(pack.get("enabled", True)):
                return False, "pack_disabled", None

            player = (data.get("players", {}) or {}).get(user_id)
            if not isinstance(player, dict):
                return False, "player_not_found", None
            user = player.get("user", {}) if isinstance(player.get("user", {}), dict) else {}
            if not isinstance(user, dict):
                return False, "player_data_invalid", None

            inventory = user.get("inventory", []) if isinstance(user.get("inventory", []), list) else []

            logger.info("[PACK_BUY] qty_used=%s", qty)
            price = int(pack.get("price", 0))
            total_cost = price * qty
            balance = _wallet_balance(user)
            if balance < total_cost:
                return False, f"insufficient_coins:{balance}:{total_cost}", None

            # Deduct coins and store packs in inventory (open via /packs)
            _set_wallet_balance(user, balance - total_cost)
            _add_packs_to_inventory(data, user_id, key, qty)

            stats = (data.get("packs", {}) or {}).setdefault("stats", {})
            if not isinstance(stats, dict):
                stats = {}
                data["packs"]["stats"] = stats
            stats["total_spent"] = int(stats.get("total_spent", 0)) + int(total_cost)

            player_packs = player.setdefault("packs", {})
            if not isinstance(player_packs, dict):
                player_packs = {}
                player["packs"] = player_packs
            player_packs["spent"] = int(player_packs.get("spent", 0)) + int(total_cost)

            return True, "ok", {"pack": pack, "quantity": qty, "total_cost": total_cost}

        ok, reason, payload = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            reason_text = str(reason)
            if reason_text.startswith("insufficient_coins:"):
                _tag, have, need = reason_text.split(":", 2)
                reason_text = f"Insufficient balance. You have {int(have):,} coins but need {int(need):,}."
            elif reason_text == "no_eligible_cards_for_pack":
                reason_text = "This pack has rates configured, but none of the weighted rarities currently have usable cards in the catalog. Add matching cards or adjust pack rates."
            elif reason_text == "pack_not_found":
                reason_text = "Pack not found."
            elif reason_text == "pack_disabled":
                reason_text = "This pack is currently disabled."
            elif reason_text == "player_not_found":
                reason_text = "Player profile not found."
            elif reason_text == "player_data_invalid":
                reason_text = "Player data is invalid."
            elif reason_text == "no_rates":
                reason_text = "This pack has no valid drop rates configured."
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Pack Buy Failed", reason_text), ephemeral=True)
            return

        assert isinstance(payload, dict)
        pack = payload["pack"]
        pack_name = str(pack.get("name", "Pack"))
        body = (
            f"**🎴 Packs Purchased!**\n"
            f"{pack_name}  ×{payload['quantity']}\n"
            f"💰 Cost: {int(payload['total_cost']):,} coins\n"
            f"Use /packs to open them!"
        )
        await smart_reply(interaction, embed=make_embed(data, f"{e('pack', data)} Pack Purchased", body))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PacksCog(bot))
