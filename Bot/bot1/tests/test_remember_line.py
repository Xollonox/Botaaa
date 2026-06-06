"""Tests for the remember_line function in bot1.main."""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add bot1 directory to path so we can import the module
bot1_dir = Path(__file__).parent.parent
sys.path.insert(0, str(bot1_dir))

# Import main module - it can be imported fine without Discord setup
import main


class TestRememberLine(unittest.TestCase):
    """Test cases for the remember_line function."""

    def setUp(self) -> None:
        """Set up test fixtures with mocked globals."""
        # Create fresh mock objects for each test
        self.mock_bot_memory = {"users": {}, "channels": {}}
        self.mock_save_json_async = AsyncMock()
        self.mock_bot_settings = {"max_user_memory_items": 80}

        # Patch all at once before each test
        self.patcher_memory = patch.object(main, "BOT_MEMORY", self.mock_bot_memory)
        self.patcher_save = patch.object(main, "_save_json_file_async", self.mock_save_json_async)
        self.patcher_settings = patch.object(main, "BOT_SETTINGS", self.mock_bot_settings)

        self.patcher_memory.start()
        self.patcher_save.start()
        self.patcher_settings.start()

    def tearDown(self) -> None:
        """Clean up patches after each test."""
        self.patcher_memory.stop()
        self.patcher_save.stop()
        self.patcher_settings.stop()

    def test_backend_error_message_returns_early(self) -> None:
        """Test that backend error messages are not appended to memory."""
        user_id = 111111111
        prefix = "B"
        line = "I could not reach the AI backend right now due to network issues"

        # Call remember_line
        asyncio.run(main.remember_line(user_id, prefix, line))

        # Verify that _save_json_file_async was NOT called (early return)
        self.mock_save_json_async.assert_not_called()

        # Verify that the line was not added to memory
        users = self.mock_bot_memory.get("users", {})
        assert not users, "Memory should be empty after early return"

    def test_backend_error_exact_match(self) -> None:
        """Test that only the exact backend error message is filtered."""
        user_id = 222222222
        prefix = "B"
        # Exact message with leading/trailing whitespace
        line = "  I could not reach the AI backend right now  "

        asyncio.run(main.remember_line(user_id, prefix, line))

        # Should have early returned, no save
        self.mock_save_json_async.assert_not_called()

    def test_user_message_appended_normally(self) -> None:
        """Test that user messages (prefix 'U') are appended normally."""
        user_id = 333333333
        prefix = "U"
        line = "This is a user message"

        asyncio.run(main.remember_line(user_id, prefix, line))

        # Verify _save_json_file_async was called (normal flow)
        self.mock_save_json_async.assert_called_once()

        # Verify the line was added to memory
        users = self.mock_bot_memory.get("users", {})
        assert len(users) == 1, "Should have one user scope"

        scope_key = f"user:{user_id}:dm"
        state = users[scope_key]
        lines = state.get("lines", [])
        assert len(lines) == 1, "Should have one line appended"
        assert "U: This is a user message" in lines[0]

    def test_bot_message_different_text_appended(self) -> None:
        """Test that bot messages with different text (not the error) are appended."""
        user_id = 444444444
        prefix = "B"
        line = "This is a different bot message"

        asyncio.run(main.remember_line(user_id, prefix, line))

        # Should have saved normally
        self.mock_save_json_async.assert_called_once()

        # Verify the line was added
        users = self.mock_bot_memory.get("users", {})
        scope_key = f"user:{user_id}:dm"
        state = users[scope_key]
        lines = state.get("lines", [])
        assert len(lines) == 1
        assert "B: This is a different bot message" in lines[0]

    def test_line_trimming_to_300_chars(self) -> None:
        """Test that long lines are trimmed to 300 characters."""
        user_id = 555555555
        prefix = "U"
        long_line = "x" * 500

        asyncio.run(main.remember_line(user_id, prefix, long_line))

        users = self.mock_bot_memory.get("users", {})
        scope_key = f"user:{user_id}:dm"
        state = users[scope_key]
        lines = state.get("lines", [])

        # Should be "U: " + 300 chars of "x"
        assert len(lines[0]) == 303, "Line should be 'U: ' (3 chars) + 300 chars content"
        assert lines[0].startswith("U: xxx")

    def test_msg_count_incremented(self) -> None:
        """Test that msg_count is incremented."""
        user_id = 666666666
        prefix = "U"

        asyncio.run(main.remember_line(user_id, prefix, "message 1"))
        asyncio.run(main.remember_line(user_id, prefix, "message 2"))

        users = self.mock_bot_memory.get("users", {})
        scope_key = f"user:{user_id}:dm"
        state = users[scope_key]

        assert state.get("msg_count") == 2

    def test_with_guild_and_channel_scope(self) -> None:
        """Test that guild_id and channel_id create proper scope."""
        user_id = 777777777
        guild_id = 888888888
        channel_id = 999999999
        prefix = "U"

        asyncio.run(main.remember_line(user_id, prefix, "test", guild_id=guild_id, channel_id=channel_id))

        users = self.mock_bot_memory.get("users", {})
        scope_key = f"user:{user_id}:guild:{guild_id}:chan:{channel_id}"

        assert scope_key in users
        state = users[scope_key]
        assert len(state.get("lines", [])) == 1


if __name__ == "__main__":
    unittest.main()
