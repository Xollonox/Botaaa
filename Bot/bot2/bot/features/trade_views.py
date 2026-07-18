"""Trade UI — helpers, modals, panel & confirm views for the trade system."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord

from bot.data.constants import rarity_icon as _ri
from bot.utils.interaction_visibility import error_reply
from bot.utils.squad_logic import get_player
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed

if TYPE_CHECKING:
    from bot.features.trades import TradesCog

logger = logging.getLogger(__name__)

TRADE_TIMEOUT = 600  # 10 minutes

TRADE_PRICE_BANDS: dict[str, tuple[int, int]] = {
    "Common":    (500,   1_000),
    "Rare":      (3_000, 5_000),
    "Epic":      (10_000, 20_000),
    "Legendary": (30_000, 40_000),
    "Mythical":  (50_000, 60_000),
    "Infernal":  (70_000, 80_000),
    "Abyssal":   (90_000, 100_000),
}


def _ago(ts: int) -> str:
    diff = now_ts() - ts
    if diff < 60:    return "just now"
    if diff < 3600:  return f"{diff//60}m ago"
    if diff < 86400: return f"{diff//3600}h ago"
    return f"{diff//86400}d ago"


def _trade_root(data: dict[str, Any]) -> dict[str, Any]:
    t = data.setdefault("trades", {})
    t.setdefault("pending", {})
    t.setdefault("history", [])
    return t


def _find_card(inv: list, card_name: str) -> dict | None:
    return next(
        (i for i in inv if isinstance(i, dict)
         and str(i.get("card_name", "")).lower() == card_name.lower()
         and not i.get("locked") and not i.get("squad_locked")
         and not i.get("market_locked") and not i.get("trade_locked")),
        None,
    )


def _lock(inv: list, uid: str) -> None:
    for i in inv:
        if isinstance(i, dict) and str(i.get("uid", "")) == uid:
            i["trade_locked"] = True


def _unlock(inv: list, uid: str) -> None:
    for i in inv:
        if isinstance(i, dict) and str(i.get("uid", "")) == uid:
            i["trade_locked"] = False


def _remove_card(inv: list, uid: str) -> dict | None:
    for idx, i in enumerate(inv):
        if isinstance(i, dict) and str(i.get("uid", "")) == uid:
            return inv.pop(idx)
    return None


def _validate(
    a_card: dict | None, a_coins: int | None,
    b_card: dict | None, b_coins: int | None,
) -> tuple[bool, str]:
    a_has = a_card is not None or (a_coins is not None and a_coins > 0)
    b_has = b_card is not None or (b_coins is not None and b_coins > 0)
    if not a_has or not b_has:
        return False, "Both sides must offer something."
    if a_card is None and b_card is None:
        return False, "❌ Coins for coins is not allowed."
    if a_card and b_card:
        ra = str(a_card.get("rarity", ""))
        rb = str(b_card.get("rarity", ""))
        if ra.lower() != rb.lower():
            return False, f"❌ Cards must be the same rarity.\n{_ri(ra)} {a_card.get('card_name','')} is **{ra}** but {_ri(rb)} {b_card.get('card_name','')} is **{rb}**."

    def _band(r: str) -> tuple[int, int]:
        return TRADE_PRICE_BANDS.get(r, (0, 999_999_999))
    if a_card and b_coins is not None:
        rarity = str(a_card.get("rarity", ""))
        mn, mx = _band(rarity)
        if b_coins < mn:
            return False, f"❌ Minimum price for **{rarity}** is **{mn:,}** coins."
        if b_coins > mx:
            return False, f"❌ Maximum price for **{rarity}** is **{mx:,}** coins."
    if b_card and a_coins is not None:
        rarity = str(b_card.get("rarity", ""))
        mn, mx = _band(rarity)
        if a_coins < mn:
            return False, f"❌ Minimum price for **{rarity}** is **{mn:,}** coins."
        if a_coins > mx:
            return False, f"❌ Maximum price for **{rarity}** is **{mx:,}** coins."
    return True, ""


def _panel_embed(session: dict[str, Any], locked_a: bool, locked_b: bool) -> discord.Embed:
    a_name = str(session.get("a_name", "?"))
    b_name = str(session.get("b_name", "?"))

    def side_text(card: dict | None, coins: int | None, locked: bool) -> str:
        if card:
            rarity = str(card.get("rarity", ""))
            name   = str(card.get("card_name", "?"))
            line   = f"{_ri(rarity)} {name}\n│   [{rarity}]"
        elif coins and coins > 0:
            line = f"💰 {coins:,} coins"
        else:
            line = "❓ Not selected"
        return line + ("  🔒" if locked else "")

    a_text = side_text(session.get("a_card"), session.get("a_coins"), locked_a)
    b_text = side_text(session.get("b_card"), session.get("b_coins"), locked_b)

    if locked_a and locked_b:
        status = "✅ Both sides ready — confirm to complete!"
    elif locked_a:
        status = f"🔒 @{a_name} locked in — waiting for @{b_name}..."
    elif locked_b:
        status = f"🔒 @{b_name} locked in — waiting for @{a_name}..."
    else:
        status = "⏳ Both sides choose what to offer..."

    body = (
        f"╭─ 🔄 Trade Negotiation\n"
        f"│ @{a_name}  ←→  @{b_name}\n"
        f"│\n"
        f"│ @{a_name} offers:        @{b_name} offers:\n"
        f"│ {a_text:<28} {b_text}\n"
        f"│\n"
        f"│ {status}\n"
        "╰────────────────"
    )
    color = 0x2ECC71 if (locked_a and locked_b) else 0x3498DB
    return make_embed(None, "LOOKISM HXCC • TRADE", body, color=color, footer="10 minute session • Rules enforced")


class CoinsModal(discord.ui.Modal, title="Offer Coins"):
    amount = discord.ui.TextInput(
        label="Amount (coins)",
        placeholder="e.g. 35000",
        min_length=1, max_length=12,
    )

    def __init__(self, panel: "TradePanel", side: str) -> None:
        super().__init__()
        self.panel = panel
        self.side  = side

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            val = int(str(self.amount.value).strip().replace(",", "").replace("k", "000"))
            if val <= 0 or val > 999_999_999: raise ValueError
        except ValueError:
            await interaction.response.send_message("Enter a valid amount.", ephemeral=True)
            return
        if self.side == "a":
            self.panel.session["a_coins"] = val
            self.panel.session["a_card"]  = None
            self.panel.locked_a = False
        else:
            self.panel.session["b_coins"] = val
            self.panel.session["b_card"]  = None
            self.panel.locked_b = False
        await self.panel._refresh(interaction)


class TradePanel(discord.ui.View):
    def __init__(
        self,
        cog:      "TradesCog",
        a_id:     str,
        b_id:     str,
        a_name:   str,
        b_name:   str,
    ) -> None:
        super().__init__(timeout=TRADE_TIMEOUT)
        self.cog      = cog
        self.a_id     = a_id
        self.b_id     = b_id
        self.locked_a = False
        self.locked_b = False
        self.message: discord.Message | None = None

        self.session: dict[str, Any] = {
            "a_id":    a_id,   "a_name":  a_name,
            "b_id":    b_id,   "b_name":  b_name,
            "a_card":  None,   "a_coins": None,
            "b_card":  None,   "b_coins": None,
            "created_at": now_ts(),
            "expires_at": now_ts() + TRADE_TIMEOUT,
        }
        self._rebuild()

    def _side(self, user_id: str) -> str | None:
        if user_id == self.a_id: return "a"
        if user_id == self.b_id: return "b"
        return None

    def _rebuild(self) -> None:
        for child in list(self.children):
            self.remove_item(child)

        data = self.cog.bot.storage.load()
        a_opts = self._card_opts(data, self.a_id)
        b_opts = self._card_opts(data, self.b_id)

        a_sel = discord.ui.Select(
            placeholder=f"🃏 @{self.session['a_name']} — select your card",
            options=a_opts or [discord.SelectOption(label="No cards available", value="none")],
            disabled=not a_opts or self.locked_a,
            row=0,
        )
        a_sel.callback = self._on_card_a
        self.add_item(a_sel)

        b_sel = discord.ui.Select(
            placeholder=f"🃏 @{self.session['b_name']} — select your card",
            options=b_opts or [discord.SelectOption(label="No cards available", value="none")],
            disabled=not b_opts or self.locked_b,
            row=1,
        )
        b_sel.callback = self._on_card_b
        self.add_item(b_sel)

        coins_a = discord.ui.Button(
            label=f"💰 @{self.session['a_name']} offer coins",
            style=discord.ButtonStyle.secondary,
            row=2, disabled=self.locked_a,
        )
        coins_a.callback = self._on_coins_a
        self.add_item(coins_a)

        coins_b = discord.ui.Button(
            label=f"💰 @{self.session['b_name']} offer coins",
            style=discord.ButtonStyle.secondary,
            row=2, disabled=self.locked_b,
        )
        coins_b.callback = self._on_coins_b
        self.add_item(coins_b)

        lock_a = discord.ui.Button(
            label=f"🔒 Lock In (@{self.session['a_name']})",
            style=discord.ButtonStyle.success,
            row=3,
            disabled=self.locked_a or (not self.session["a_card"] and not self.session["a_coins"]),
        )
        lock_a.callback = self._on_lock_a
        self.add_item(lock_a)

        lock_b = discord.ui.Button(
            label=f"🔒 Lock In (@{self.session['b_name']})",
            style=discord.ButtonStyle.success,
            row=3,
            disabled=self.locked_b or (not self.session["b_card"] and not self.session["b_coins"]),
        )
        lock_b.callback = self._on_lock_b
        self.add_item(lock_b)

        cancel = discord.ui.Button(
            label="❌ Cancel", style=discord.ButtonStyle.danger, row=3,
        )
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    def _card_opts(self, data: dict[str, Any], user_id: str) -> list[discord.SelectOption]:
        player = get_player(data, user_id)
        if not isinstance(player, dict):
            return []
        inv = player.get("user", {}).get("inventory", [])
        if not isinstance(inv, list):
            return []
        seen: set[str] = set()
        opts: list[discord.SelectOption] = []
        for item in inv:
            if not isinstance(item, dict):
                continue
            if item.get("locked") or item.get("squad_locked") or item.get("market_locked") or item.get("trade_locked"):
                continue
            name   = str(item.get("card_name", ""))
            rarity = str(item.get("rarity", ""))
            uid    = str(item.get("uid", ""))
            if not name or uid in seen:
                continue
            seen.add(uid)
            opts.append(discord.SelectOption(
                label=f"{_ri(rarity)} {name}  [{rarity}]"[:100],
                value=uid,
                description=f"{rarity}",
            ))
            if len(opts) >= 25:
                break
        return opts

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) not in (self.a_id, self.b_id):
            await interaction.response.send_message("This trade session isn't yours.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            for side_id, side_card_key in ((self.a_id, "a_card"), (self.b_id, "b_card")):
                card = self.session.get(side_card_key)
                if isinstance(card, dict):
                    player = get_player(data, side_id)
                    if isinstance(player, dict):
                        inv = player.get("user", {}).get("inventory", [])
                        _unlock(inv, str(card.get("uid", "")))
            t = _trade_root(data)
            t["pending"].pop(self.a_id, None)
            t["pending"].pop(self.b_id, None)
        self.cog.bot.storage.with_lock(mutate)
        await self.cog.bot.trade_service.remove_pending_pair(self.a_id, self.b_id, mirror_json=False)
        self.cog.unregister_panel(self)
        if self.message:
            try:
                e = make_embed(None, "LOOKISM HXCC • TRADE", "╭─ ⏰ Trade Expired\n│ Session timed out.\n╰────────────────", color=0x636E72)
                await self.message.edit(embed=e, view=None)
            except Exception:
                logger.exception("Failed to edit expired trade panel message")

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._rebuild()
        embed = _panel_embed(self.session, self.locked_a, self.locked_b)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_card_a(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.a_id:
            await error_reply(interaction, "Not your side.")
            return
        uid = interaction.data["values"][0]
        if uid == "none":
            await interaction.response.defer()
            return
        data = self.cog.bot.storage.load()
        player = get_player(data, self.a_id)
        inv = player.get("user", {}).get("inventory", []) if player else []
        card = next((i for i in inv if isinstance(i, dict) and str(i.get("uid","")) == uid), None)
        if card:
            self.session["a_card"]  = dict(card)
            self.session["a_coins"] = None
            self.locked_a = False
        await self._refresh(interaction)

    async def _on_card_b(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.b_id:
            await error_reply(interaction, "Not your side.")
            return
        uid = interaction.data["values"][0]
        if uid == "none":
            await interaction.response.defer()
            return
        data = self.cog.bot.storage.load()
        player = get_player(data, self.b_id)
        inv = player.get("user", {}).get("inventory", []) if player else []
        card = next((i for i in inv if isinstance(i, dict) and str(i.get("uid","")) == uid), None)
        if card:
            self.session["b_card"]  = dict(card)
            self.session["b_coins"] = None
            self.locked_b = False
        await self._refresh(interaction)

    async def _on_coins_a(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.a_id:
            await error_reply(interaction, "Not your side.")
            return
        await interaction.response.send_modal(CoinsModal(self, "a"))

    async def _on_coins_b(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.b_id:
            await error_reply(interaction, "Not your side.")
            return
        await interaction.response.send_modal(CoinsModal(self, "b"))

    async def _on_lock_a(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.a_id:
            await error_reply(interaction, "Not your side.")
            return
        self.locked_a = True
        await self._maybe_confirm(interaction)

    async def _on_lock_b(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.b_id:
            await error_reply(interaction, "Not your side.")
            return
        self.locked_b = True
        await self._maybe_confirm(interaction)

    async def _maybe_confirm(self, interaction: discord.Interaction) -> None:
        if not (self.locked_a and self.locked_b):
            await self._refresh(interaction)
            return

        ok, err = _validate(
            self.session.get("a_card"), self.session.get("a_coins"),
            self.session.get("b_card"), self.session.get("b_coins"),
        )
        if not ok:
            self.locked_a = False
            self.locked_b = False
            await interaction.response.send_message(err, ephemeral=True)
            return

        confirm_view = ConfirmView(self.cog, self)
        embed = _panel_embed(self.session, True, True)
        await interaction.response.edit_message(embed=embed, view=confirm_view)
        confirm_view.message = interaction.message

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        def mutate(data: dict[str, Any]) -> None:
            for side_id, key in ((self.a_id, "a_card"), (self.b_id, "b_card")):
                card = self.session.get(key)
                if isinstance(card, dict):
                    player = get_player(data, side_id)
                    if isinstance(player, dict):
                        _unlock(player.get("user", {}).get("inventory", []), str(card.get("uid", "")))
            t = _trade_root(data)
            t["pending"].pop(self.a_id, None)
            t["pending"].pop(self.b_id, None)
        self.cog.bot.storage.with_lock(mutate)
        await self.cog.bot.trade_service.remove_pending_pair(self.a_id, self.b_id, mirror_json=False)
        self.cog.unregister_panel(self)
        self.stop()
        e = make_embed(None, "LOOKISM HXCC • TRADE", f"╭─ 🚫 Trade Cancelled\n│ Cancelled by @{interaction.user.name}\n╰────────────────", color=0xE74C3C)
        await interaction.response.edit_message(embed=e, view=None)


class ConfirmView(discord.ui.View):
    def __init__(self, cog: "TradesCog", panel: TradePanel) -> None:
        super().__init__(timeout=120)
        self.cog     = cog
        self.panel   = panel
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        uid = str(interaction.user.id)
        if uid not in (self.panel.a_id, self.panel.b_id):
            await error_reply(interaction, "Not your trade.")
            return False
        return True

    @discord.ui.button(label="✅ Confirm Trade", style=discord.ButtonStyle.success, row=0)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = str(interaction.user.id)
        if not hasattr(self, "_confirmed"):
            self._confirmed: set[str] = set()
        self._confirmed.add(uid)

        if len(self._confirmed) < 2:
            other_name = self.panel.session["b_name"] if uid == self.panel.a_id else self.panel.session["a_name"]
            await interaction.response.send_message(
                f"✅ You confirmed! Waiting for @{other_name} to confirm too...",
                ephemeral=True,
            )
            return

        s = self.panel.session
        a_id = self.panel.a_id
        b_id = self.panel.b_id

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            a_player = get_player(data, a_id)
            b_player = get_player(data, b_id)
            if not isinstance(a_player, dict) or not isinstance(b_player, dict):
                return False, "player_not_found"

            a_user = a_player.get("user", {})
            b_user = b_player.get("user", {})
            a_inv  = a_user.get("inventory", [])
            b_inv  = b_user.get("inventory", [])

            a_card  = s.get("a_card")
            a_coins = s.get("a_coins") or 0
            b_card  = s.get("b_card")
            b_coins = s.get("b_coins") or 0

            if a_coins > 0:
                a_bal = int(a_user.get("balance", 0))
                if a_bal < a_coins:
                    return False, f"insufficient_a:{a_bal}:{a_coins}"
            if b_coins > 0:
                b_bal = int(b_user.get("balance", 0))
                if b_bal < b_coins:
                    return False, f"insufficient_b:{b_bal}:{b_coins}"

            if isinstance(a_card, dict):
                real = _remove_card(a_inv, str(a_card.get("uid", "")))
                if not real:
                    return False, "a_card_missing"
                real["trade_locked"] = False
                real["squad_locked"] = False
                b_inv.append(real)

            if isinstance(b_card, dict):
                real = _remove_card(b_inv, str(b_card.get("uid", "")))
                if not real:
                    return False, "b_card_missing"
                real["trade_locked"] = False
                real["squad_locked"] = False
                a_inv.append(real)

            if a_coins > 0:
                a_user["balance"] = int(a_user.get("balance", 0)) - a_coins
                b_user["balance"] = int(b_user.get("balance", 0)) + a_coins
            if b_coins > 0:
                b_user["balance"] = int(b_user.get("balance", 0)) - b_coins
                a_user["balance"] = int(a_user.get("balance", 0)) + b_coins

            t = _trade_root(data)
            t["pending"].pop(a_id, None)
            t["pending"].pop(b_id, None)
            return True, "ok"

        ok, reason = self.cog.bot.storage.with_lock(mutate)
        if ok:
            try:
                await self.cog.bot.trade_service.append_history({
                    **s,
                    "status": "accepted",
                    "resolved_at": now_ts(),
                })
            except Exception:
                # History is audit metadata; never leave users pending after the
                # already-persisted card/coin exchange succeeds.
                logger.exception("Failed to append completed trade history")
            try:
                await self.cog.bot.trade_service.remove_pending_pair(a_id, b_id, mirror_json=False)
            except Exception:
                logger.exception("Failed to clear SQLite pending rows after completed trade")
            self.cog.unregister_panel(self.panel)
        self.stop()

        if not ok:
            msgs = {
                "player_not_found": "A player profile was not found.",
                "a_card_missing":   f"@{s['a_name']}'s card is no longer available.",
                "b_card_missing":   f"@{s['b_name']}'s card is no longer available.",
            }
            msg = msgs.get(reason, reason)
            if reason.startswith("insufficient_a:"):
                _, have, need = reason.split(":")
                msg = f"@{s['a_name']} doesn't have enough coins ({int(have):,} / {int(need):,})."
            elif reason.startswith("insufficient_b:"):
                _, have, need = reason.split(":")
                msg = f"@{s['b_name']} doesn't have enough coins ({int(have):,} / {int(need):,})."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        a_gave = f"{_ri(s['a_card']['rarity'])} {s['a_card']['card_name']}" if s.get("a_card") else f"💰 {int(s.get('a_coins',0)):,} coins"
        b_gave = f"{_ri(s['b_card']['rarity'])} {s['b_card']['card_name']}" if s.get("b_card") else f"💰 {int(s.get('b_coins',0)):,} coins"
        body = (
            f"╭─ ✅ Trade Complete!\n"
            f"│ @{s['a_name']} gave:  {a_gave}\n"
            f"│ @{s['b_name']} gave:  {b_gave}\n"
            "╰────────────────"
        )
        embed = make_embed(None, "LOOKISM HXCC • TRADE", body, color=0x2ECC71)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="✏️ Edit Offer", style=discord.ButtonStyle.secondary, row=0)
    async def edit_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.panel.locked_a = False
        self.panel.locked_b = False
        self.panel._rebuild()
        embed = _panel_embed(self.panel.session, False, False)
        await interaction.response.edit_message(embed=embed, view=self.panel)
        self.panel.message = interaction.message

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        def mutate(data: dict[str, Any]) -> None:
            for sid, key in ((self.panel.a_id, "a_card"), (self.panel.b_id, "b_card")):
                card = self.panel.session.get(key)
                if isinstance(card, dict):
                    p = get_player(data, sid)
                    if isinstance(p, dict):
                        _unlock(p.get("user", {}).get("inventory", []), str(card.get("uid", "")))
            t = _trade_root(data)
            t["pending"].pop(self.panel.a_id, None)
            t["pending"].pop(self.panel.b_id, None)
        self.cog.bot.storage.with_lock(mutate)
        await self.cog.bot.trade_service.remove_pending_pair(self.panel.a_id, self.panel.b_id, mirror_json=False)
        self.cog.unregister_panel(self.panel)
        self.stop()
        e = make_embed(None, "LOOKISM HXCC • TRADE", f"╭─ 🚫 Trade Cancelled\n│ Cancelled by @{interaction.user.name}\n╰────────────────", color=0xE74C3C)
        await interaction.response.edit_message(embed=e, view=None)


def _history_embed_rows(user_id: str, username: str, rows: list[dict[str, Any]]) -> discord.Embed:
    mine = list(rows[:20])
    if not mine:
        body = "╭─ 📜 Trade History\n│ No trades yet.\n╰────────────────"
        return make_embed(None, "LOOKISM HXCC • TRADE", body, color=0x2B2D31)

    STATUS_ICONS = {"accepted": "✅", "declined": "❌", "cancelled": "🚫", "expired": "⏰"}
    lines = []
    for i, h in enumerate(mine[:10], 1):
        icon  = STATUS_ICONS.get(str(h.get("status", "")), "•")
        other = str(h.get("b_name", "?")) if str(h.get("a_id", "")) == user_id else str(h.get("a_name", "?"))
        ts    = int(h.get("resolved_at", h.get("created_at", 0)))
        a_gave = f"{h['a_card']['card_name']}" if h.get("a_card") else f"💰{int(h.get('a_coins',0)):,}"
        b_gave = f"{h['b_card']['card_name']}" if h.get("b_card") else f"💰{int(h.get('b_coins',0)):,}"
        lines.append(f"│ {i}. {icon} {a_gave} ↔ {b_gave}  •  @{other}  •  {_ago(ts)}")

    body = f"╭─ 📜 Trade History — @{username}\n" + "\n".join(lines) + "\n╰────────────────"
    return make_embed(None, "LOOKISM HXCC • TRADE", body, color=0x2B2D31, footer="Last 10 trades")
