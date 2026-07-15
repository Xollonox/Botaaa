from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock

import discord
import main
from neetverse.guide import GUIDE_PAGES


def test_bot_loads_expected_discord_systems_without_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "bot.sqlite3")
    monkeypatch.setattr(main, "GUILD_IDS", ())
    bot = main.NeetVerseBot()
    bot.tree.sync = AsyncMock(return_value=[])

    asyncio.run(bot.setup_hook())

    versions = bot.curriculum_service.list_versions()
    assert versions[0]["target_year"] == 2026
    assert versions[0]["node_count"] == 783

    names = {command.name for command in bot.tree.get_commands()}
    assert {
        "start", "profile", "study", "ai", "voice", "practice", "mistake", "revision",
        "resource", "progress", "task", "plan", "goal", "mock", "ranking", "today", "streak", "discipline", "reminders", "lecture", "news", "syllabus", "mydata", "stats", "help",
    } <= names

    def endpoints(command, prefix=""):
        full_name = f"{prefix} {command.name}".strip()
        children = getattr(command, "commands", None)
        if children:
            return [leaf for child in children for leaf in endpoints(child, full_name)]
        return [full_name]

    registered = {
        leaf for command in bot.tree.get_commands() for leaf in endpoints(command)
    }
    documented = {
        match
        for _, description in GUIDE_PAGES
        for match in re.findall(r"`/([^`]+)`", description)
    }
    assert len(registered) == 67
    assert documented == registered


def test_on_ready_uses_a_supported_discord_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "bot.sqlite3")
    bot = main.NeetVerseBot()
    bot.change_presence = AsyncMock()

    asyncio.run(bot.on_ready())

    activity = bot.change_presence.await_args.kwargs["activity"]
    assert activity.type is discord.ActivityType.watching
    assert activity.name == "NEET preparation"
