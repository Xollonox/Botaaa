"""Redeem code commands."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import discord
from discord.ext import commands

from bot.utils.checks import ensure_registered, is_owner
from bot.utils.redeem_logic import can_use, format_reward, is_expired, list_codes_lines, normalize_code, validate_code_format
from bot.utils.reward_grant import grant_reward
from bot.utils.timeutil import now_ts
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply


class RedeemListView(discord.ui.View):
    def __init__(self, data: dict[str, Any], lines: list[str], user_id: str) -> None:
        super().__init__(timeout=120)
        self.data = data
        self.lines = lines
        self.user_id = user_id
        self.page = 0
        self.page_size = 10

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await smart_reply(interaction, 
                embed=make_embed(self.data, f"{e('warning', self.data)} Not allowed", "Only the command invoker can use this menu."),
                ephemeral=True,
            )
            return False
        return True

    def _embed(self) -> discord.Embed:
        total_pages = max(1, math.ceil(max(1, len(self.lines)) / self.page_size))
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.page_size
        chunk = self.lines[start : start + self.page_size]

        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= total_pages - 1

        return make_embed(
            self.data,
            f"{e('list', self.data)} Redeem Codes",
            "\n".join(chunk) if chunk else f"{e('info', self.data)} No codes found.",
            fields=[(f"{e('page', self.data)} Page", f"{self.page + 1}/{total_pages}", False)],
        )

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page -= 1
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page += 1
        await interaction.response.edit_message(embed=self._embed(), view=self)


class RedeemCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._attempts: dict[str, list[int]] = defaultdict(list)

    def _rate_limited(self, user_id: str) -> tuple[bool, int]:
        now_value = now_ts()
        window = now_value - 30
        logs = [ts for ts in self._attempts.get(user_id, []) if ts >= window]
        self._attempts[user_id] = logs
        if len(logs) >= 3:
            return True, max(0, 30 - (now_value - logs[0]))
        logs.append(now_value)
        self._attempts[user_id] = logs
        return False, 0

    def _owner_embed(self, data: dict[str, Any]) -> discord.Embed:
        return make_embed(data, f"{e('no', data)} Owner Only", "You are not allowed to use this command.")

    @commands.command(name="redeem")
    async def redeem(self, ctx: commands.Context, *, code: str) -> None:
        if not await ensure_registered(ctx, self.bot.storage):
            return

        user_id = str(ctx.author.id)
        limited, retry_in = self._rate_limited(user_id)
        data = self.bot.storage.load()
        if limited:
            await smart_reply(ctx,
                embed=make_embed(
                    data,
                    f"{e('limit', data)} Redeem Rate Limited",
                    f"{e('time', data)} Try again in {retry_in}s.",
                ),
                ephemeral=True,
            )
            return

        normalized = normalize_code(code)

        def mutate(state: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None, int | None]:
            redeem_codes = state.get("redeem_codes", {})
            if not isinstance(redeem_codes, dict):
                state["redeem_codes"] = {}
                redeem_codes = state["redeem_codes"]

            row = redeem_codes.get(normalized)
            if not isinstance(row, dict):
                return False, "Code not found.", None, None

            expires_at = int(row.get("expires_at", 0))
            if is_expired(expires_at):
                return False, "Code is expired.", row, None

            if not can_use(row):
                return False, "Code usage limit reached.", row, None

            players = state.get("players", {})
            player = players.get(user_id, {}) if isinstance(players, dict) else {}
            if not isinstance(player, dict):
                return False, "Player not found.", row, None

            redeemed = player.setdefault("redeemed_codes", {})
            if not isinstance(redeemed, dict):
                player["redeemed_codes"] = {}
                redeemed = player["redeemed_codes"]

            if normalized in redeemed:
                return False, "You already redeemed this code.", row, None

            reward = row.get("reward", {})
            if not isinstance(reward, dict):
                return False, "Invalid reward config.", row, None

            reward_type = str(reward.get("type", ""))
            mapped_type = "premium" if reward_type == "premium_currency" else reward_type
            ok, message = grant_reward(state, user_id, {
                "reward_type": mapped_type,
                "reward_value": reward.get("value"),
            })
            if not ok:
                return False, message, row, None

            now_value = now_ts()
            row["uses"] = int(row.get("uses", 0)) + 1
            redeemed[normalized] = now_value

            remaining = None
            max_uses = int(row.get("max_uses", 0))
            if max_uses > 0:
                remaining = max_uses - int(row.get("uses", 0))

            return True, "Code redeemed successfully.", row, remaining

        ok, message, code_row, remaining = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()

        if not ok:
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('warning', data)} Redeem Failed", message),
                ephemeral=True,
            )
            return

        reward_text = format_reward(data, code_row.get("reward", {}) if isinstance(code_row, dict) else {})
        fields = [(f"{e('reward', data)} Claimed", reward_text, False)]
        if remaining is not None:
            fields.append((f"{e('uses', data)} Remaining", str(max(0, int(remaining))), False))

        await smart_reply(ctx,
            embed=make_embed(data, f"{e('redeem', data)} Redeem",
                box("Claimed", [f"✅ {reward_text}"] + [f"{n}: {v}" for n, v, _ in (fields or [])])),
            ephemeral=True,
        )

    @commands.command(name="o_redeem_create")
    async def o_redeem_create(
        self,
        ctx: commands.Context,
        code: str,
        reward_type: str,
        reward_value: str,
        expires_in_hours: int = 0,
        max_uses: int = 0,
        note: str | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=self._owner_embed(data), ephemeral=True)
            return

        normalized = normalize_code(code)
        valid, error = validate_code_format(normalized)
        if not valid:
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('warning', data)} Invalid Code", error),
                ephemeral=True,
            )
            return

        created_at = now_ts()
        expires_at = created_at + int(expires_in_hours) * 3600 if int(expires_in_hours) > 0 else 0

        def mutate(state: dict[str, Any]) -> tuple[bool, str]:
            redeem_codes = state.get("redeem_codes", {})
            if not isinstance(redeem_codes, dict):
                state["redeem_codes"] = {}
                redeem_codes = state["redeem_codes"]

            if normalized in redeem_codes:
                return False, "Code already exists."

            redeem_codes[normalized] = {
                "code": normalized,
                "created_at": created_at,
                "expires_at": int(expires_at),
                "max_uses": int(max_uses),
                "uses": 0,
                "reward": {"type": str(reward_type), "value": reward_value},
                "note": str(note or ""),
            }
            return True, "Code created."

        ok, message = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(ctx,
                embed=make_embed(data, f"{e('warning', data)} Create Failed", message),
                ephemeral=True,
            )
            return

        reward_preview = format_reward(data, {"type": reward_type, "value": reward_value})
        expiry_text = "never" if expires_at == 0 else f"<t:{expires_at}:R>"
        uses_text = "unlimited" if int(max_uses) == 0 else str(int(max_uses))
        await smart_reply(ctx,
            embed=make_embed(
                data,
                f"{e('create', data)} Redeem Code Created",
                f"{e('code', data)} `{normalized}`",
                fields=[
                    (f"{e('reward', data)} Reward", reward_preview, False),
                    (f"{e('time', data)} Expires", expiry_text, False),
                    (f"{e('uses', data)} Max Uses", uses_text, False),
                ],
            ),
            ephemeral=True,
        )

    @commands.command(name="o_redeem_delete")
    async def o_redeem_delete(self, ctx: commands.Context, *, code: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=self._owner_embed(data), ephemeral=True)
            return

        normalized = normalize_code(code)

        def mutate(state: dict[str, Any]) -> bool:
            redeem_codes = state.get("redeem_codes", {})
            if not isinstance(redeem_codes, dict):
                state["redeem_codes"] = {}
                return False
            return redeem_codes.pop(normalized, None) is not None

        deleted = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        title = f"{e('delete', data)} Code Deleted" if deleted else f"{e('warning', data)} Delete Failed"
        desc = f"{e('code', data)} `{normalized}` removed." if deleted else "Code not found."
        await smart_reply(ctx, embed=make_embed(data, title, desc), ephemeral=True)

    @commands.command(name="o_redeem_list")
    async def o_redeem_list(self, ctx: commands.Context, *, filter: str | None = None) -> None:
        data = self.bot.storage.load()
        if not is_owner(ctx):
            await smart_reply(ctx, embed=self._owner_embed(data), ephemeral=True)
            return

        lines = list_codes_lines(data)
        if filter:
            needle = normalize_code(filter)
            lines = [line for line in lines if needle in line.upper()]

        view = RedeemListView(data, lines, str(ctx.author.id))
        await smart_reply(ctx, embed=view._embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RedeemCog(bot))
