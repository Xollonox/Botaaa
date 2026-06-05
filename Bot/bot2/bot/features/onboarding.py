"""Onboarding, Terms, and help commands for Lookism Bot v2."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import OWNER_IDS
from bot.data.defaults import build_default_player
from bot.features.help_index import HELP_CATEGORIES
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed, skin_embed
from bot.features.packs import grant_newbie_packs
from bot.utils.interaction_visibility import smart_reply, error_reply

TERMS_COLOR = 0xE11D48
STARTER_COINS = 1000
STARTER_NEWBIE_PACKS = 3


def has_user_accepted_terms(data: dict[str, Any], user_id: str) -> bool:
    players = data.get("players", {})
    if not isinstance(players, dict):
        return False
    player = players.get(str(user_id))
    if not isinstance(player, dict):
        return False
    user = player.get("user", {})
    if not isinstance(user, dict):
        return False
    return bool(user.get("tos_accepted", False))


def build_terms_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ LOOKISM HXCC • Access",
        color=TERMS_COLOR,
        description=(
            "**TERMS OF SERVICE**\n\n"
            "╭─ Rules\n"
            "│ • Respect all users\n"
            "│ • No harassment or hate speech\n"
            "│ • Exploiting bugs is prohibited\n"
            "│ • Alt-account farming is not allowed\n"
            "╰────────────────\n"
            "╭─ Data Notice\n"
            "│ • Player progress is stored securely\n"
            "│ • Game economy may change for balance\n"
            "│ • Abuse may result in account reset\n"
            "╰────────────────\n"
            "╭─ Access Requirement\n"
            "│ Accept these terms before using commands.\n"
            "╰────────────────"
        ),
    )
    embed.set_footer(text="Terms of Service")
    return embed


def build_start_embed(username: str) -> discord.Embed:
    embed = discord.Embed(
        title="LOOKISM HXCC • Account",
        color=TERMS_COLOR,
        description=(
            "**ACCOUNT INITIALIZED**\n\n"
            f"Welcome, {username}\n\n"
            "╭─ Starter Package\n"
            f"│ Coins: {STARTER_COINS}\n"
            "│ Gems: 0\n"
            "╰────────────────\n"
            "╭─ Your Journey\n"
            "│ • Collect fighters\n"
            "│ • Build squads\n"
            "│ • Battle opponents\n"
            "│ • Climb league ranks\n"
            "╰────────────────\n"
            "╭─ Begin\n"
            "│ /help\n"
            "│ 📖 /tutorial — Complete the tutorial for bonus rewards!\n"
            "│ /shop\n"
            "│ Buy packs from the /shop panel\n"
            "│ /squad\n"
            "│ /battle\n"
            "╰────────────────"
        ),
    )
    embed.set_footer(text="Account Registration")
    return embed


def build_about_embed() -> discord.Embed:
    embed = discord.Embed(
        title="LOOKISM HXCC • System",
        color=TERMS_COLOR,
        description=(
            "**SYSTEM OVERVIEW**\n\n"
            "╭─ Combat\n"
            "│ Ranked squad battles\n"
            "│ Competitive leagues\n"
            "│ PvP progression\n"
            "╰────────────────\n"
            "╭─ Cards\n"
            "│ Collect powerful fighters\n"
            "│ Upgrade star levels\n"
            "│ Build squads for battle\n"
            "╰────────────────\n"
            "╭─ Economy\n"
            "│ Player market trading\n"
            "│ Official store and pack rolls\n"
            "│ Hourly / daily / weekly rewards\n"
            "╰────────────────\n"
            "╭─ Social\n"
            "│ Create or join gangs\n"
            "│ Seasonal milestones\n"
            "│ Achievements and leaderboards\n"
            "╰────────────────\n"
            "╭─ Quick Start\n"
            "│ /start\n"
            "│ /help\n"
            "│ /shop\n"
            "│ Buy packs from the /shop panel\n"
            "│ /squad\n"
            "│ /battle\n"
            "╰────────────────"
        ),
    )
    embed.set_footer(text="System Info")
    return embed


def _pack_count(player: dict[str, Any], pack_key: str) -> int:
    packs = player.get("pack_inventory")
    if isinstance(packs, dict):
        return int(packs.get(pack_key, 0))
    user = player.get("user", {})
    inv = user.get("pack_inventory", []) if isinstance(user, dict) else []
    if isinstance(inv, list):
        total = 0
        for item in inv:
            if isinstance(item, dict) and str(item.get("key", "")) == pack_key:
                total += int(item.get("quantity", item.get("qty", 1)))
        return total
    return 0


def _starter_already_granted(player: dict[str, Any]) -> bool:
    user = player.get("user", {})
    if not isinstance(user, dict):
        return False
    if bool(user.get("starter_granted", False)):
        return True
    has_progress = (
        int(user.get("balance", user.get("coins", 0)) or 0) > 0
        or bool(user.get("inventory"))
        or _pack_count(player, "newbie_pack") > 0
    )
    return has_progress


def ensure_started_player(
    data: dict[str, Any],
    user_id: str,
    username: str,
    *,
    accept_terms: bool,
) -> tuple[dict[str, Any], bool]:
    players = data.setdefault("players", {})
    player = players.get(user_id)
    if not isinstance(player, dict):
        player = build_default_player(user_id, username, now_ts())
        players[user_id] = player

    user = player.get("user")
    if not isinstance(user, dict):
        user = {}
        player["user"] = user

    user["id"] = user_id
    user["name"] = username
    if accept_terms:
        user["tos_accepted"] = True

    granted = False
    if not _starter_already_granted(player):
        user["balance"] = max(int(user.get("balance", user.get("coins", 0)) or 0), STARTER_COINS)
        user["premium_balance"] = max(int(user.get("premium_balance", 0) or 0), 0)
        grant_newbie_packs(data, user_id)
        granted = True
    user["starter_granted"] = True
    return player, granted


class TermsGateView(discord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = int(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return int(interaction.user.id) == self.user_id

    @discord.ui.button(label="✔ Accept Terms", style=discord.ButtonStyle.success, row=0)
    async def accept_terms(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        user_id = str(interaction.user.id)
        username = interaction.user.name

        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            ensure_started_player(data, user_id, username, accept_terms=True)
            return data

        self.bot.storage.with_lock(mutate)
        # Warm the bot-level terms cache so subsequent commands skip storage.load()
        if hasattr(self.bot, "mark_terms_accepted"):
            self.bot.mark_terms_accepted(interaction.user.id)
        if interaction.response.is_done():
            await interaction.followup.send("Terms accepted successfully.")
        else:
            await interaction.response.send_message("Terms accepted successfully.")

    @discord.ui.button(label="▶ Start", style=discord.ButtonStyle.primary, row=0)
    async def start_panel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        data = self.bot.storage.load()
        if not has_user_accepted_terms(data, str(interaction.user.id)):
            if interaction.response.is_done():
                await interaction.followup.send("You must accept the terms first.")
            else:
                await interaction.response.send_message("You must accept the terms first.")
            return

        embed = build_start_embed(interaction.user.name)
        view = StartQuickLinksView(self.bot)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)




class StartQuickLinksView(discord.ui.View):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=180)
        self.bot = bot

    @discord.ui.button(label="📜 Terms", style=discord.ButtonStyle.secondary, row=0)
    async def terms_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_terms_embed()
        view = TermsGateView(self.bot, interaction.user.id)
        await smart_reply(interaction, embed=embed, view=view)

    @discord.ui.button(label="📘 About", style=discord.ButtonStyle.primary, row=0)
    async def about_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_about_embed()
        await smart_reply(interaction, embed=embed)


def _is_owner_category(category: dict[str, Any]) -> bool:
    name = str(category.get("name", "")).lower()
    if "owner" in name or "admin" in name:
        return True
    items = category.get("items", [])
    if isinstance(items, list):
        for cmd, _ in items:
            if str(cmd).strip().startswith("/o_"):
                return True
    return False


class HelpPaginatorView(discord.ui.View):
    def __init__(self, invoker_id: int, data: dict[str, Any], *, timeout: float = 120) -> None:
        super().__init__(timeout=timeout)
        self.invoker_id = invoker_id
        self.data = data
        self.page = 0
        is_owner_user = int(invoker_id) in OWNER_IDS
        self.categories = [c for c in HELP_CATEGORIES if is_owner_user or not _is_owner_category(c)]
        self.total = len(self.categories)
        self.message: discord.Message | None = None
        self._refresh_buttons()
        self.category_select.options = [
            discord.SelectOption(label=str(cat.get("name", "Category"))[:100], value=str(i))
            for i, cat in enumerate(self.categories[:25])
        ]
        self.category_select.placeholder = "Jump to category"

    def _refresh_buttons(self) -> None:
        at_start = self.page <= 0
        at_end = self.page >= self.total - 1
        self.prev_button.disabled = at_start
        self.next_button.disabled = at_end
        self.home_button.disabled = at_start

    def _chunk_lines(self, lines: list[str], limit: int = 1000) -> list[str]:
        chunks: list[str] = []
        current = ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > limit:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks or [f"{e('dot', self.data)} No commands in this category yet."]

    def _build_embed(self) -> discord.Embed:
        cat = self.categories[self.page]
        cat_emoji = e(cat.get("emoji_key", "info"), self.data)
        sep = e("line", self.data)
        dot = e("dot", self.data)
        box = e("box", self.data)

        title = f"{e('help', self.data)}  Help Hub  \u2022  {cat['name']}"

        description = (
            f"{sep * 3}\n"
            f"{cat_emoji}  **{cat['name']}**  \u2014  Page `{self.page + 1}` of `{self.total}`\n"
            f"{sep * 3}"
        )

        lines = [f"{dot} `{cmd}` \u2014 {desc}" for cmd, desc in cat["items"]]
        chunks = self._chunk_lines(lines)

        fields: list[tuple[str, str, bool]] = []
        for idx, chunk in enumerate(chunks[:3], start=1):
            label = f"{box} Commands" if len(chunks) == 1 else f"{box} Commands  ({idx})"
            fields.append((label, chunk, False))

        embed = make_embed(self.data, title, description, variant="premium", fields=fields)
        return skin_embed(embed, data=self.data)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await smart_reply(
                interaction,
                embed=make_embed(
                    self.data,
                    f"{e('warning', self.data)}  Access Locked",
                    (
                        f"{e('line', self.data)}\n"
                        f"{e('box', self.data)}  This menu belongs to another user.\n"
                        f"{e('dot', self.data)}  Use `/help` to open your own panel."
                    ),
                ),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="\u25c4  Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="\u2302 Home", style=discord.ButtonStyle.secondary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = 0
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next  \u25ba", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


    @discord.ui.select(placeholder="Jump to category", min_values=1, max_values=1, options=[discord.SelectOption(label="Loading...", value="0")], row=1)
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        try:
            self.page = max(0, min(int(select.values[0]), self.total - 1))
        except Exception:
            self.page = 0
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


class OnboardingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="start", description="Open your account panel.")
    async def start(self, interaction: discord.Interaction) -> None:
        user_id = str(interaction.user.id)
        username = interaction.user.name

        result = {"granted": False}

        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            _player, granted = ensure_started_player(data, user_id, username, accept_terms=True)
            result["granted"] = granted
            return data

        self.bot.storage.with_lock(mutate)
        granted = result["granted"]

        # Warm the bot-level terms cache so subsequent commands skip storage.load()
        if hasattr(self.bot, "mark_terms_accepted"):
            self.bot.mark_terms_accepted(interaction.user.id)

        embed = build_start_embed(interaction.user.name)
        view = StartQuickLinksView(self.bot)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)


    @app_commands.command(name="help", description="Browse all commands by category.")
    async def help(self, interaction: discord.Interaction) -> None:
        data = self.bot.storage.load()
        view = HelpPaginatorView(interaction.user.id, data, timeout=120)
        await smart_reply(interaction, embed=view._build_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OnboardingCog(bot))
