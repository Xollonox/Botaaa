"""/stats_guide — player-facing explanation of the damage pipeline and character typings."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.ui import make_embed
from bot.utils.typing_matchup import TYPES, MASTERMIND_BIQ_BONUS, MASTERMIND_IQ_BONUS, relations_table


def _pipeline_embed() -> discord.Embed:
    body = (
        "**Damage is computed in this order:**\n"
        "```\n"
        "1. Miss check          : if attacker.biq < defender.biq, roll for miss\n"
        "2. Base roll           : strength/2 ± range by move type\n"
        "                         normal ±5 | special +20..+45\n"
        "                         ultimate 3x..4x | unique +40..+80\n"
        "3. Strength bonus      : +10/+15/+30 if Strength mastery (by move)\n"
        "4. Technique multiplier: 1.04..1.30 (higher moves = bigger boost)\n"
        "5. Attacker IQ scaling : × (1 + iq/500)\n"
        "6. Defender IQ scaling : × (1 − iq/500)\n"
        "7. Typing multiplier   : × Π(attacker_type → defender_type)\n"
        "8. Defensive typing    : × Tank/Fighter/Brawler incoming reductions\n"
        "9. Defense reaction    : Block / Dodge / Parry / Revert / Tank-DR\n"
        "```\n"
        f"**Mastermind passive** (per card): +{MASTERMIND_IQ_BONUS} effective IQ "
        f"and +{MASTERMIND_BIQ_BONUS} effective BIQ while active.\n"
    )
    return make_embed(None, "LOOKISM HXCC • STATS GUIDE", body, color=0xE11D48, footer="How damage works")


def _typing_embed() -> discord.Embed:
    lines = ["**Character Typings:** " + " / ".join(TYPES), "", "**Matchup chart:**", "```"]
    lines.append(f"{'Attacker':<11} → {'Defender':<11}  out   in")
    for at, dt, off, dfn in relations_table():
        lines.append(f"{at:<11} → {dt:<11}  ×{off:<4} ×{dfn:<4}")
    lines.append("```")
    lines.append(
        "**Rules for 2-type cards:**\n"
        "• For each pair (attacker_type × defender_type), the matching factor multiplies in.\n"
        "• If both cards share the same two types, all effects nullify (×1.00).\n"
        "• Mastermind has no matchup relations — its bonus is a passive IQ/BIQ boost."
    )
    return make_embed(None, "LOOKISM HXCC • TYPING CHART", "\n".join(lines), color=0xE11D48, footer="Counter-play")


class _GuideView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.page = 0

    @discord.ui.button(label="Pipeline", style=discord.ButtonStyle.secondary)
    async def go_pipeline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 0
        await interaction.response.edit_message(embed=_pipeline_embed(), view=self)

    @discord.ui.button(label="Typing chart", style=discord.ButtonStyle.secondary)
    async def go_typing(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 1
        await interaction.response.edit_message(embed=_typing_embed(), view=self)


class StatsGuideCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="stats_guide", description="Show the damage pipeline and the character typing matchup chart.")
    async def stats_guide(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=_pipeline_embed(), view=_GuideView(), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsGuideCog(bot))
