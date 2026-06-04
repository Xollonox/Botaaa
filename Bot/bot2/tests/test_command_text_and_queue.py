from __future__ import annotations

import inspect

from bot.features import help_index
from bot.features.battle import RANKED_QUEUE_TIMEOUT_SECONDS


def test_ranked_queue_timeout_matches_cpu_fallback_window() -> None:
    assert RANKED_QUEUE_TIMEOUT_SECONDS == 60


def test_help_uses_registered_group_command_names() -> None:
    commands = [cmd for category in help_index.HELP_CATEGORIES for cmd, _desc in category["items"]]

    assert "/market browse" in commands
    assert "/market add" in commands
    assert "/market remove" in commands
    assert "/trade start" in commands
    assert "/trade cancel" in commands
    assert "/trade history" in commands
    assert "/browse" not in commands
    assert "/add" not in commands
    assert "/remove" not in commands


def test_onboarding_no_longer_points_to_missing_pack_buy_command() -> None:
    from bot.features import onboarding

    source = inspect.getsource(onboarding)
    assert "/pack buy" not in source
