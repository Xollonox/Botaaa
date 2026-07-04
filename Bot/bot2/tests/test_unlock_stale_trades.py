"""Tests for LookismBot._unlock_stale_trades clean-vs-crash paths.

The method is a bound coroutine on LookismBot but only touches ``self.storage``
and the module-level CLEAN_SHUTDOWN_MARKER path, so we exercise it via an
unbound call against a minimal stand-in with a real ``Storage`` seeded on disk.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types

# Load Bot/bot2/main.py explicitly (not Bot/bot1/main.py which shares the name).
_BOT2_MAIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
)
_spec = importlib.util.spec_from_file_location("bot2_main", _BOT2_MAIN_PATH)
main = importlib.util.module_from_spec(_spec)
sys.modules["bot2_main"] = main
_spec.loader.exec_module(main)
from bot.data.storage import Storage


def _seed_storage(storage: Storage) -> None:
    def mutate(data: dict) -> None:
        data["players"] = {
            "1": {
                "user": {
                    "inventory": [
                        {"uid": "a", "trade_locked": True},
                        {"uid": "b", "trade_locked": False},
                    ]
                }
            },
        }
        data.setdefault("trades", {})["pending"] = {
            "t1": {"initiator": "1", "recipient": "2", "status": "pending"},
        }

    storage.with_lock(mutate)


def _run(storage: Storage) -> None:
    stub = types.SimpleNamespace(storage=storage)
    asyncio.run(main.LookismBot._unlock_stale_trades(stub))


def test_clean_shutdown_preserves_trades_and_locks(tmp_path, monkeypatch) -> None:
    marker = tmp_path / ".clean_shutdown"
    marker.write_text("ok")
    monkeypatch.setattr(main, "CLEAN_SHUTDOWN_MARKER", str(marker))

    storage = Storage(str(tmp_path / "data.json"))
    _seed_storage(storage)

    _run(storage)

    # Marker is removed so a subsequent boot sees a "crash".
    assert not marker.exists()

    data = storage.load()
    # Pending trade untouched.
    assert data["trades"]["pending"]["t1"]["status"] == "pending"
    # trade_locked flags NOT flipped.
    inv = data["players"]["1"]["user"]["inventory"]
    assert inv[0]["trade_locked"] is True
    assert inv[1]["trade_locked"] is False


def test_crash_recovery_unlocks_but_preserves_pending(tmp_path, monkeypatch) -> None:
    marker = tmp_path / ".clean_shutdown"
    # marker file is absent → crash recovery path.
    assert not marker.exists()
    monkeypatch.setattr(main, "CLEAN_SHUTDOWN_MARKER", str(marker))

    storage = Storage(str(tmp_path / "data.json"))
    _seed_storage(storage)

    _run(storage)

    data = storage.load()
    # Pending trades preserved despite crash.
    assert data["trades"]["pending"]["t1"]["status"] == "pending"
    # trade_locked=True flipped to False; already-False left alone.
    inv = data["players"]["1"]["user"]["inventory"]
    assert inv[0]["trade_locked"] is False
    assert inv[1]["trade_locked"] is False
