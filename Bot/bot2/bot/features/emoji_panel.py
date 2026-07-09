"""Owner emoji panel — server emoji dropdown."""
from __future__ import annotations
from typing import Any

import discord
from discord.ext import commands

from bot.utils.checks import is_owner
from bot.utils.ui import box, e, list_keys, make_embed, reset_emoji, set_emoji, reset_all_emojis
from bot.utils.interaction_visibility import smart_reply

PAGE_SIZE   = 20


def _server_emoji_opts(guild: discord.Guild | None, offset: int = 0) -> list[discord.SelectOption]:
    if not guild:
        return []
    opts = []
    for em in list(guild.emojis)[offset: offset + 25]:
        opts.append(discord.SelectOption(
            label=em.name[:100],
            value=str(em),
            emoji=em,
            description=f"<:{em.name}:{em.id}>"[:100],
        ))
    return opts


class EmojiPanelView(discord.ui.View):

    def __init__(self, cog: "EmojiPanelCog", owner_id: str, data: dict[str, Any], guild: discord.Guild | None) -> None:
        discord.ui.View.__init__(self, timeout=300)
        self._skip_style_view = True
        self.cog      = cog
        self.owner_id = owner_id
        self.guild    = guild
        self.page     = 0
        self.keys     = sorted(list_keys(data))
        self.sel_key  = self.keys[0] if self.keys else ""
        self._build(data)

    # ── helpers ───────────────────────────────────────────────────

    def _max_page(self) -> int:
        return max(0, (len(self.keys) - 1) // PAGE_SIZE)

    def _page_keys(self) -> list[str]:
        return self.keys[self.page * PAGE_SIZE: (self.page + 1) * PAGE_SIZE]

    def _clear(self) -> None:
        for item in list(self.children):
            discord.ui.View.remove_item(self, item)

    def _add(self, item: discord.ui.Item) -> None:
        discord.ui.View.add_item(self, item)

    def _build(self, data: dict[str, Any]) -> None:
        self._clear()
        total_server = len(self.guild.emojis) if self.guild else 0

        # ── Row 0: key select ─────────────────────────────────────
        key_opts = []
        for k in self._page_keys():
            cur = e(k, data)
            key_opts.append(discord.SelectOption(
                label=k[:100],
                description=f"Now: {cur}"[:100],
                value=k,
                default=(k == self.sel_key),
            ))
        if not key_opts:
            key_opts = [discord.SelectOption(label="—", value="__empty__")]
        key_sel = discord.ui.Select(placeholder="Select emoji key", options=key_opts, row=0)
        key_sel.callback = self._on_key
        self._add(key_sel)

        # ── Row 1: server emojis 1–25 ─────────────────────────────
        opts1 = _server_emoji_opts(self.guild, 0)
        sel1  = discord.ui.Select(
            placeholder="Pick server emoji (1–25)" if opts1 else "No server emojis",
            options=opts1 or [discord.SelectOption(label="—", value="__none__")],
            disabled=not opts1 or not self.sel_key,
            row=1,
        )
        sel1.callback = self._on_emoji
        self._add(sel1)

        # ── Row 2: server emojis 26–50 (only if server has > 25) ──
        if total_server > 25:
            opts2 = _server_emoji_opts(self.guild, 25)
            sel2  = discord.ui.Select(
                placeholder=f"Pick server emoji (26–{min(50, total_server)})",
                options=opts2 or [discord.SelectOption(label="—", value="__none__")],
                disabled=not opts2 or not self.sel_key,
                row=2,
            )
            sel2.callback = self._on_emoji
            self._add(sel2)
            btn_row = 3
        else:
            btn_row = 2

        # ── Buttons ───────────────────────────────────────────────
        prev = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=btn_row, disabled=self.page <= 0)
        nxt  = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary,   row=btn_row, disabled=self.page >= self._max_page())
        rst  = discord.ui.Button(label="↩ Reset", style=discord.ButtonStyle.danger,   row=btn_row, disabled=not self.sel_key)
        prev.callback = self._on_prev
        nxt.callback  = self._on_next
        rst.callback  = self._on_reset
        self._add(prev)
        self._add(nxt)
        self._add(rst)

    def _embed(self, data: dict[str, Any]) -> discord.Embed:
        lines = ["━━━━━━━━━━━━━━━━━━"]
        for i, k in enumerate(self._page_keys(), 1):
            tag = " ◀" if k == self.sel_key else ""
            lines.append(f"[{i:02d}] `{k}`  →  {e(k, data)}{tag}")
        if not self._page_keys():
            lines.append("No keys.")
        if self.sel_key:
            lines += ["━━━━━━━━━━━━━━━━━━",
                      f"Editing: `{self.sel_key}`  →  {e(self.sel_key, data)}",
                      "Pick a server emoji above to assign."]
        pg = f"Page {self.page+1}/{self._max_page()+1}"
        return make_embed(data, f"{e('panel', data)} Emoji Panel  •  {pg}", box("Keys", lines))

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message("Not your panel.", ephemeral=True)
        return False

    # ── callbacks ─────────────────────────────────────────────────

    async def _on_key(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction): return
        v = interaction.data["values"][0]
        if v == "__empty__": await interaction.response.defer(); return
        await interaction.response.defer()
        self.sel_key = v
        data = self.cog.bot.storage.load()
        self._build(data)
        await interaction.edit_original_response(embed=self._embed(data), view=self)

    async def _on_emoji(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction): return
        chosen = interaction.data["values"][0]
        if chosen == "__none__" or not self.sel_key: await interaction.response.defer(); return
        await interaction.response.defer()
        key = self.sel_key
        self.cog.bot.storage.with_lock(lambda d: set_emoji(d, key, chosen))
        data = self.cog.bot.storage.load()
        self.keys = sorted(list_keys(data))
        self._build(data)
        await interaction.edit_original_response(embed=self._embed(data), view=self)

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction): return
        await interaction.response.defer()
        self.page = max(0, self.page - 1)
        data = self.cog.bot.storage.load()
        self.keys = sorted(list_keys(data))
        self._build(data)
        await interaction.edit_original_response(embed=self._embed(data), view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction): return
        await interaction.response.defer()
        self.page = min(self._max_page(), self.page + 1)
        data = self.cog.bot.storage.load()
        self.keys = sorted(list_keys(data))
        self._build(data)
        await interaction.edit_original_response(embed=self._embed(data), view=self)

    async def _on_reset(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction): return
        if not self.sel_key: await interaction.response.defer(); return
        await interaction.response.defer()
        key = self.sel_key
        self.cog.bot.storage.with_lock(lambda d: reset_emoji(d, key))
        data = self.cog.bot.storage.load()
        self.keys = sorted(list_keys(data))
        self._build(data)
        await interaction.edit_original_response(embed=self._embed(data), view=self)


class EmojiPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="o_emoji_panel")
    async def o_emoji_panel(self, ctx: commands.Context) -> None:
        if not is_owner(ctx):
            await ctx.send("Owner only.")
            return
        data = self.bot.storage.load()
        view = EmojiPanelView(self, str(ctx.author.id), data, ctx.guild)
        await smart_reply(ctx, embed=view._embed(data), view=view, ephemeral=True)

    @commands.command(name="o_emoji_set")
    async def o_emoji_set(self, ctx: commands.Context, key: str, emoji: str) -> None:
        if not is_owner(ctx):
            await ctx.send("Owner only.")
            return
        k, v = str(key).strip().lower(), str(emoji).strip()
        self.bot.storage.with_lock(lambda d: set_emoji(d, k, v))
        data = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('ok',data)} Emoji Updated", f"Set `{k}` → {v}"), ephemeral=True)

    @commands.command(name="o_emoji_reset")
    async def o_emoji_reset(self, ctx: commands.Context, key: str) -> None:
        if not is_owner(ctx):
            await ctx.send("Owner only.")
            return
        k = str(key).strip().lower()
        self.bot.storage.with_lock(lambda d: reset_emoji(d, k))
        data = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('ok',data)} Emoji Reset", f"Reset `{k}` → {e(k,data)}"), ephemeral=True)

    @commands.command(name="o_emoji_reset_all")
    async def o_emoji_reset_all(self, ctx: commands.Context) -> None:
        if not is_owner(ctx):
            await ctx.send("Owner only.")
            return
        count = self.bot.storage.with_lock(lambda d: reset_all_emojis(d))
        data  = self.bot.storage.load()
        await smart_reply(ctx, embed=make_embed(data, f"{e('ok',data)} All Reset", f"Reset {count} keys to defaults."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmojiPanelCog(bot))
