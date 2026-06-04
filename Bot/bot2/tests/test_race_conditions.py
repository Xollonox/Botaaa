"""Tests for concurrent storage mutations via with_lock."""

from __future__ import annotations

import threading

from bot.data.storage import Storage


def test_concurrent_increments_no_lost_updates(tmp_path) -> None:
    storage = Storage(str(tmp_path / "data.json"))
    n_threads = 8
    increments_per_thread = 50

    def worker() -> None:
        for _ in range(increments_per_thread):
            def mutate(data: dict) -> None:
                players = data.setdefault("players", {})
                u = players.setdefault("123", {"user": {"balance": 0}})
                u["user"]["balance"] = int(u["user"].get("balance", 0)) + 1
            storage.with_lock(mutate)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = storage.load()
    assert final["players"]["123"]["user"]["balance"] == n_threads * increments_per_thread


def test_check_then_set_inside_mutate_is_atomic(tmp_path) -> None:
    """Pattern used by /trade start: reserve a slot only if not already taken."""
    storage = Storage(str(tmp_path / "data.json"))
    wins = []

    def try_reserve() -> None:
        def mutate(data: dict) -> bool:
            pending = data.setdefault("trades", {}).setdefault("pending", {})
            if "user-a" in pending:
                return False
            pending["user-a"] = True
            return True
        if storage.with_lock(mutate):
            wins.append(1)

    threads = [threading.Thread(target=try_reserve) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(wins) == 1
