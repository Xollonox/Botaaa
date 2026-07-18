"""Guided tutorial quest chain for new players."""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands


TUTORIAL_STEPS = {
    1: {
        "title": "Step 1: Open Your First Pack",
        "desc": "**Mission**\nOpen any pack from `/shop`\nYou have 3 newbie packs ready!\n\nUse `/shop` → select a pack → Open!",
        "reward": "🎉 +200 coins",
        "action": "open_pack",
    },
    2: {
        "title": "Step 2: Build Your Squad",
        "desc": "**Mission**\nAdd a card to your squad\nUse `/squad assign`",
        "reward": "🎉 +300 coins",
        "action": "assign_squad",
    },
    3: {
        "title": "Step 3: Your First Battle",
        "desc": "**Mission**\nWin your first battle!\nUse `/battle` to fight a CPU opponent",
        "reward": "🎉 +500 coins + 1 Amateur Pack",
        "action": "win_battle",
    },
    4: {
        "title": "Step 4: Claim Your Daily Reward",
        "desc": "**Mission**\nUse `/daily` to claim your reward\nCome back every day to build a streak!",
        "reward": "🎉 +200 coins",
        "action": "claim_daily",
    },
    5: {
        "title": "Step 5: Check Your Achievements",
        "desc": "**Mission**\nUse `/achievements` to see your goals\nComplete them for bonus CP and rewards!",
        "reward": "🎉 +1000 coins + 🏆 Graduate Badge",
        "action": "view_achievements",
    },
}

TUTORIAL_COMPLETE_REWARD = {"coins": 3000, "badge": "Graduate"}


def get_tutorial_step(user: dict) -> int:
    """Get current tutorial step (0-5+)."""
    return user.get("tutorial", {}).get("step", 0)


def is_tutorial_complete(user: dict) -> bool:
    """Check if tutorial is complete."""
    return user.get("tutorial", {}).get("completed", False)


def advance_tutorial(user: dict, action: str) -> dict | None:
    """Call when player completes an action. Returns step dict if advanced, None if not."""
    tut = user.setdefault("tutorial", {"step": 0, "completed": False})
    if tut.get("completed"):
        return None

    current_step = tut.get("step", 0)

    action_to_step = {
        "open_pack": 1,
        "assign_squad": 2,
        "win_battle": 3,
        "claim_daily": 4,
        "view_achievements": 5,
    }

    required_step = action_to_step.get(action)
    if required_step is None:
        return None

    if current_step + 1 != required_step:
        return None

    tut["step"] = required_step

    if required_step == 3:
        user.setdefault("pending_milestone_packs", []).append("amateur_pack")

    if required_step == 5:
        tut["completed"] = True
        user["balance"] = user.get("balance", 0) + TUTORIAL_COMPLETE_REWARD["coins"]
        user.setdefault("badges", [])
        if TUTORIAL_COMPLETE_REWARD["badge"] not in user["badges"]:
            user["badges"].append(TUTORIAL_COMPLETE_REWARD["badge"])

    return TUTORIAL_STEPS.get(required_step)


def build_tutorial_embed(step: int) -> discord.Embed:
    """Build tutorial progress embed."""
    if step == 0:
        info = {"title": "Welcome! Let's Start", "desc": "Use `/start` to begin your journey!"}
    elif step > 5:
        return discord.Embed(
            title="✅ Tutorial Complete!",
            description="You've mastered the basics! Go conquer the leagues.",
            color=0x27ae60
        )
    else:
        info = TUTORIAL_STEPS.get(step, TUTORIAL_STEPS[1])

    return discord.Embed(
        title=f"📖 Tutorial — {info['title']}",
        description=info['desc'],
        color=0xF39C12,
    )


class TutorialCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @discord.app_commands.command(name="tutorial", description="View your tutorial progress.")
    async def tutorial_cmd(self, interaction: discord.Interaction) -> None:
        data = self.bot.storage.load()
        player = data.get("players", {}).get(str(interaction.user.id))
        if not player:
            await interaction.response.send_message("Use `/start` first!", ephemeral=True)
            return
        user = player.get("user", {})
        step = get_tutorial_step(user)

        if step == 4:
            def mutate(d: dict[str, Any]) -> dict[str, Any]:
                p = d.get("players", {}).get(str(interaction.user.id), {})
                u = p.get("user", {})
                advance_tutorial(u, "view_achievements")
                return d
            self.bot.storage.with_lock(mutate)
            step = 5

        embed = build_tutorial_embed(step if step < 6 else 6)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TutorialCog(bot))
