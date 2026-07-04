"""Tests for llm.chat_with_fallback error-sentinel handling.

The wrapper clients (OpenAICompatClient, OllamaClient) turn empty/unparseable
provider responses into a sentinel string prefixed by ERROR_BACKEND_UNREACHABLE.
``chat_with_fallback`` must NOT return that sentinel as a success — it should
detect it and try the next backend in the chain.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Make bot1 importable, same pattern as test_remember_line.py
bot1_dir = Path(__file__).parent.parent
sys.path.insert(0, str(bot1_dir))

import llm  # noqa: E402


class TestChatWithFallback(unittest.TestCase):
    """Ensure sentinel responses cascade through the backend chain."""

    def _sentinel(self, tail: str = "empty") -> str:
        return f"{llm.ERROR_BACKEND_UNREACHABLE} ({tail})"

    def test_empty_ollama_response_falls_through_to_cerebras(self) -> None:
        """Ollama returns the empty-response sentinel → cerebras is called."""
        sentinel = self._sentinel("Empty Ollama response")
        with patch.object(llm.ollama_client, "chat", new=AsyncMock(return_value=sentinel)) as ollama_mock, \
             patch.object(llm.cerebras_client, "chat", new=AsyncMock(return_value="hello from cerebras")) as cerebras_mock, \
             patch.object(llm.groq_client, "chat", new=AsyncMock(return_value="hello from groq")) as groq_mock:
            reply = asyncio.run(llm.chat_with_fallback("sys", "user"))

        # Fallback took over — the sentinel is NOT the final reply.
        self.assertNotIn(llm.ERROR_BACKEND_UNREACHABLE, reply)
        self.assertEqual(reply, "hello from cerebras")
        ollama_mock.assert_awaited()
        cerebras_mock.assert_awaited()
        groq_mock.assert_not_awaited()

    def test_all_backends_sentinel_returns_last_attempt(self) -> None:
        """Every backend returns a sentinel — final reply is whatever the last backend produced,
        confirming the code actually tried them all rather than short-circuiting on the first sentinel."""
        s1 = self._sentinel("Empty Ollama response")
        s2 = self._sentinel("Empty or unparseable response")
        s3 = self._sentinel("Empty or unparseable response — groq")

        with patch.object(llm.ollama_client, "chat", new=AsyncMock(return_value=s1)) as ollama_mock, \
             patch.object(llm.cerebras_client, "chat", new=AsyncMock(return_value=s2)) as cerebras_mock, \
             patch.object(llm.groq_client, "chat", new=AsyncMock(return_value=s3)) as groq_mock, \
             patch.object(llm.groq_client, "keys", ["fake-key"]):
            reply = asyncio.run(llm.chat_with_fallback("sys", "user"))

        # Every backend was tried in order.
        ollama_mock.assert_awaited()
        cerebras_mock.assert_awaited()
        groq_mock.assert_awaited()
        # Result is groq's sentinel (all we had left) — but critically the code
        # did not accept the earlier sentinels as success.
        self.assertEqual(reply, s3)

    def test_ollama_success_short_circuits(self) -> None:
        """Ollama returning a real reply skips all fallbacks."""
        with patch.object(llm.ollama_client, "chat", new=AsyncMock(return_value="ollama ok")) as ollama_mock, \
             patch.object(llm.cerebras_client, "chat", new=AsyncMock()) as cerebras_mock, \
             patch.object(llm.groq_client, "chat", new=AsyncMock()) as groq_mock:
            reply = asyncio.run(llm.chat_with_fallback("sys", "user"))

        self.assertEqual(reply, "ollama ok")
        ollama_mock.assert_awaited_once()
        cerebras_mock.assert_not_awaited()
        groq_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
