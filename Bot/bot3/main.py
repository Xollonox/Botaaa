"""Tester Bot v3 — AI-powered QA observer for Lookism HXCC (bot2).

This bot uses DeepSeek v4 Flash to autonomously test bot2 commands,
observe responses, and generate bug/UX reports. It does NOT contain
game logic — it's purely an observability & testing layer.

Usage:
  @bot3 test <suite>    — Run a test suite against bot2
  @bot3 report          — Generate latest AI bug report
  @bot3 observe #channel — Watch a channel for bot2 interactions
  @bot3 analyze         — AI-analyze bot2's last response
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

import discord
from discord.ext import commands

# Load .env if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_TOKEN: str = os.environ.get("TESTER_TOKEN", "")
DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
BOT2_USER_ID: int = int(os.environ.get("BOT2_USER_ID", "0"))  # Lookism bot's user ID
OBSERVE_CHANNEL_IDS: list[int] = [
    int(c) for c in os.environ.get("OBSERVE_CHANNELS", "").split(",") if c
]
REPORT_CHANNEL_ID: int = int(os.environ.get("REPORT_CHANNEL", "0"))
OWNER_IDS: set[int] = {
    int(i) for i in os.environ.get("OWNER_IDS", "").split(",") if i
}

if not BOT_TOKEN:
    raise RuntimeError("TESTER_TOKEN not set")
if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY not set")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tester")

# ---------------------------------------------------------------------------
# Test suites — command lists to run against bot2
# ---------------------------------------------------------------------------
TEST_SUITES: dict[str, list[dict]] = {
    "onboarding": [
        {"cmd": "/start",                      "desc": "Account creation",          "expect": "ACCOUNT INITIALIZED"},
        {"cmd": "/help",                       "desc": "Help menu opens",           "expect": "Help Hub"},
    ],
    "economy": [
        {"cmd": "/balance",                    "desc": "Check balance",             "expect": "WALLET"},
        {"cmd": "/daily",                      "desc": "Claim daily reward",        "expect": "DAILY"},
        {"cmd": "/weekly",                     "desc": "Claim weekly reward",       "expect": "WEEKLY"},
        {"cmd": "/hourly",                     "desc": "Claim hourly reward",       "expect": "HOURLY"},
    ],
    "profile": [
        {"cmd": "/profile",                    "desc": "View own profile",          "expect": "Player Profile"},
        {"cmd": "/card_info card_name:Kitae Kim Busan", "desc": "Look up a card",   "expect": "FIGHTER"},
        {"cmd": "/collection",                 "desc": "Open collection",           "expect": "COLLECTION"},
    ],
    "squad": [
        {"cmd": "/squad",                      "desc": "Open squad panel",          "expect": "SQUAD"},
    ],
    "battle": [
        {"cmd": "/battle",                     "desc": "Queue for battle",          "expect": "QUEUE"},
        {"cmd": "/battle_cancel",              "desc": "Cancel queue",              "expect": "cancelled"},
        {"cmd": "/friendly user:@me",           "desc": "Friendly challenge",       "expect": "friendly"},
        {"cmd": "/forfeit",                    "desc": "Forfeit battle",            "expect": "forfeit"},
    ],
    "market": [
        {"cmd": "/market browse",              "desc": "Browse market",             "expect": "MARKET"},
    ],
    "social": [
        {"cmd": "/gang info",                  "desc": "Gang info",                 "expect": "GANGS"},
        {"cmd": "/alliance info",              "desc": "Alliance info",             "expect": "ALLIANCE"},
        {"cmd": "/lb global",                  "desc": "Leaderboard",               "expect": "LEADERBOARD"},
    ],
    "full": [],  # populated at runtime with all suites
}

# Populate "full" suite
for suite_name, tests in TEST_SUITES.items():
    if suite_name != "full":
        TEST_SUITES["full"].extend(tests)

# ---------------------------------------------------------------------------
# DeepSeek client
# ---------------------------------------------------------------------------
class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def chat(self, system: str, user: str) -> str:
        import aiohttp
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 2000,
                    },
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"DeepSeek API error {resp.status}: {text[:200]}")
                        return f"[DeepSeek error: {resp.status}]"
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.exception("DeepSeek call failed")
            return f"[DeepSeek error: {e}]"


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
class TesterBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            owner_ids=OWNER_IDS,
            help_command=None,
        )
        self.deepseek = DeepSeekClient(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
        self.bot2_id = BOT2_USER_ID
        self.observe_bots: set[int] = set()
        self.test_results: list[dict] = []
        self.observed_responses: list[dict] = []
        self.observe_channels: set[int] = set(OBSERVE_CHANNEL_IDS)
        self.report_channel_id = REPORT_CHANNEL_ID
        self.testing_in_progress: bool = False

    async def setup_hook(self):
        await self.add_cog(TesterCog(self))
        await self.tree.sync()
        logger.info("Tester bot synced & ready")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id if self.user else '?'})")
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="Lookism HXCC | @me to test",
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_message(self, message: discord.Message):
        if message.author.bot and message.author.id in (self.bot2_id, *self.observe_bots):
            # Capture bot responses in observed channels
            if message.channel.id in self.observe_channels:
                self.observed_responses.append({
                    "bot_id": message.author.id,
                    "bot_name": message.author.name,
                    "channel_id": message.channel.id,
                    "channel_name": message.channel.name,
                    "content": message.content or "[embed]",
                    "embeds": [e.to_dict() for e in message.embeds] if message.embeds else [],
                    "timestamp": datetime.utcnow().isoformat(),
                })
                # Keep last 50
                self.observed_responses = self.observed_responses[-50:]

        await self.process_commands(message)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------
class TesterCog(commands.Cog):
    def __init__(self, bot: TesterBot):
        self.bot = bot

    # ── /test ────────────────────────────────────────────────────────
    @discord.app_commands.command(name="test", description="Run a test suite against a bot")
    @discord.app_commands.describe(
        suite="Test suite to run",
        target_bot="Mention the bot to test (default: Lookism HXCC)",
    )
    @discord.app_commands.choices(suite=[
        discord.app_commands.Choice(name=s.capitalize(), value=s)
        for s in TEST_SUITES.keys()
    ])
    async def test(self, interaction: discord.Interaction, suite: discord.app_commands.Choice[str], target_bot: discord.User | None = None):
        if self.bot.testing_in_progress:
            await interaction.response.send_message("⚠️ A test is already running. Wait for it to finish.", ephemeral=True)
            return

        target_id = target_bot.id if target_bot else self.bot.bot2_id
        target_name = target_bot.name if target_bot else "Lookism HXCC"

        suite_name = suite.value
        tests = TEST_SUITES.get(suite_name, [])
        if not tests:
            await interaction.response.send_message(f"❌ No tests found for '{suite_name}'", ephemeral=True)
            return

        self.bot.testing_in_progress = True
        self.bot.test_results = []
        await interaction.response.send_message(
            f"🧪 **Testing {target_name}** — Suite: {suite_name.upper()} ({len(tests)} tests)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        results = []
        passed = 0
        failed = 0
        for i, test in enumerate(tests):
            msg = await interaction.channel.send(
                f"`[{i+1}/{len(tests)}]` Testing **{test['cmd']}** — {test['desc']}..."
            )
            await asyncio.sleep(1.5)

            # Check if target bot responded in observed responses
            found = False
            for obs in reversed(self.bot.observed_responses):
                if obs.get("bot_id") != target_id:
                    continue
                content_text = obs.get("content", "")
                embed_text = ""
                for emb in obs.get("embeds", []):
                    embed_text += json.dumps(emb)
                combined = (content_text + " " + embed_text).lower()
                if test["expect"].lower() in combined:
                    found = True
                    break

            result = {
                "test": test["cmd"],
                "description": test["desc"],
                "passed": found,
                "expected": test["expect"],
            }
            results.append(result)
            self.bot.test_results.append(result)

            if found:
                passed += 1
                await msg.edit(content=f"`[{i+1}/{len(tests)}]` ✅ **{test['cmd']}** — PASS")
            else:
                failed += 1
                await msg.edit(content=f"`[{i+1}/{len(tests)}]` ❌ **{test['cmd']}** — FAIL (expected '{test['expect']}')")

            await asyncio.sleep(0.5)

        self.bot.testing_in_progress = False

        # Summary embed
        embed = discord.Embed(
            title=f"🧪 Test Suite: {suite_name.upper()}",
            description=f"**{passed} passed** · **{failed} failed** · **{len(tests)} total**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=0x2ECC71 if failed == 0 else 0xE74C3C,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text="Tester Bot v3 · DeepSeek powered")

        if failed > 0:
            fail_lines = []
            for r in results:
                if not r["passed"]:
                    fail_lines.append(f"❌ `{r['test']}` — expected `{r['expected']}`")
            if fail_lines:
                embed.add_field(
                    name="Failed Tests",
                    value="\n".join(fail_lines[:5]),
                    inline=False,
                )

        # AI analysis
        embed.add_field(
            name="🤖 AI Analysis",
            value="Running DeepSeek analysis...",
            inline=False,
        )
        analysis_msg = await interaction.channel.send(embed=embed)

        # Get DeepSeek analysis
        system_prompt = """You are a QA tester for a Discord game bot called Lookism HXCC.
Analyze test results and identify:
1. Patterns in failures
2. Potential UX issues
3. Command reliability
4. Suggestions for fixes

Be concise, specific, and actionable. Output in markdown."""

        user_prompt = f"""Test Suite: {suite_name}
Results:
{json.dumps(results, indent=2)}

Observed bot2 responses during testing:
{json.dumps(self.bot.observed_responses[-10:], indent=2)}

Generate a QA report."""
        analysis = await self.bot.deepseek.chat(system_prompt, user_prompt)

        embed.remove_field(-1)  # remove placeholder
        embed.add_field(
            name="🤖 AI Analysis",
            value=analysis[:1024],
            inline=False,
        )
        if len(analysis) > 1024:
            embed.add_field(name="_continued_", value=analysis[1024:2048], inline=False)

        await analysis_msg.edit(embed=embed)

    # ── /report ──────────────────────────────────────────────────────
    @discord.app_commands.command(name="report", description="Generate AI-powered QA report from all observed data")
    async def report(self, interaction: discord.Interaction):
        await interaction.response.defer()

        system_prompt = """You are a QA engineer for Lookism HXCC Discord bot.
Generate a comprehensive bug/UX report from the test results and observed bot responses.

Format:
## Summary
[overall health score out of 10]

## Bugs Found
- [bug description] (severity: high/medium/low)

## UX Issues
- [issue description]

## Recommendations
- [actionable fix suggestion]

Be honest. If everything looks good, say so."""

        user_prompt = json.dumps({
            "test_results": self.bot.test_results[-30:],
            "observed_responses": self.bot.observed_responses[-20:],
            "total_tests_run": len(self.bot.test_results),
            "total_observations": len(self.bot.observed_responses),
        }, indent=2)

        analysis = await self.bot.deepseek.chat(system_prompt, user_prompt)

        embed = discord.Embed(
            title="📋 QA Report — Lookism HXCC",
            description=analysis[:4096] if len(analysis) > 4096 else analysis,
            color=0x3498DB,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text="Tester Bot · DeepSeek v4 Flash")

        if len(analysis) > 4096:
            # Send as file
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📋 QA Report",
                    description="Report too long for embed. See attached file.",
                    color=0x3498DB,
                ),
                file=discord.File(
                    io.BytesIO(analysis.encode()),
                    filename="qa_report.md",
                ),
            )
        else:
            await interaction.followup.send(embed=embed)

    # ── /observe ─────────────────────────────────────────────────────
    @discord.app_commands.command(name="observe", description="Watch a bot's responses in a channel")
    @discord.app_commands.describe(
        channel="Channel to observe",
        target_bot="Mention the bot to watch",
        enable="Enable or disable observation",
    )
    async def observe(self, interaction: discord.Interaction, channel: discord.TextChannel, target_bot: discord.User | None = None, enable: bool = True):
        bot_id = target_bot.id if target_bot else self.bot.bot2_id
        bot_name = target_bot.name if target_bot else "Lookism HXCC"

        if enable:
            self.bot.observe_channels.add(channel.id)
            self.bot.observe_bots.add(bot_id)
            await interaction.response.send_message(
                f"👁️ Watching **{bot_name}** in #{channel.name}",
                ephemeral=True,
            )
        else:
            self.bot.observe_channels.discard(channel.id)
            self.bot.observe_bots.discard(bot_id)
            await interaction.response.send_message(
                f"👁️ Stopped watching **{bot_name}** in #{channel.name}",
                ephemeral=True,
            )

    # ── /analyze ─────────────────────────────────────────────────────
    @discord.app_commands.command(name="analyze", description="AI-analyze bot2's last response")
    async def analyze(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.bot.observed_responses:
            await interaction.followup.send("❌ No bot2 responses captured yet. Make sure I'm observing a channel where bot2 is active.")
            return

        last = self.bot.observed_responses[-1]
        system_prompt = """You are a QA bot. Analyze the following Discord bot response.
Identify:
1. Any errors or bugs visible in the response
2. UX quality (clarity, formatting, usefulness)
3. Missing information
4. Potential improvements

Output a concise analysis."""

        user_prompt = json.dumps(last, indent=2)
        analysis = await self.bot.deepseek.chat(system_prompt, user_prompt)

        embed = discord.Embed(
            title="🤖 Response Analysis",
            description=analysis[:4096],
            color=0x9B59B6,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Analyzing response from #{last.get('channel_name','?')}")
        await interaction.followup.send(embed=embed)

    # ── /status ──────────────────────────────────────────────────────
    @discord.app_commands.command(name="status", description="Tester bot status")
    async def status(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔧 Tester Bot Status",
            color=0x2B2D31,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Tests Run", value=str(len(self.bot.test_results)), inline=True)
        embed.add_field(name="Observed Responses", value=str(len(self.bot.observed_responses)), inline=True)
        embed.add_field(name="Watching Channels", value=str(len(self.bot.observe_channels)), inline=True)
        embed.add_field(name="DeepSeek Model", value=DEEPSEEK_MODEL, inline=True)
        embed.add_field(name="Bot2 ID", value=str(self.bot.bot2_id), inline=True)
        embed.add_field(name="Testing In Progress", value=str(self.bot.testing_in_progress), inline=True)
        embed.set_footer(text="Tester Bot v3")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Entry point with io import
# ---------------------------------------------------------------------------
import io

async def main():
    bot = TesterBot()
    async with bot:
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
