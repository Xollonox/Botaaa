"""Tests for JSON storage cache safety."""

from __future__ import annotations

from bot.data.storage import Storage


def test_load_returns_snapshot_not_live_cache(tmp_path) -> None:
    storage = Storage(str(tmp_path / "data.json"))
    first = storage.load()
    first.setdefault("players", {})["123"] = {"user": {"balance": 999}}

    second = storage.load()

    assert "123" not in second.get("players", {})


def test_with_lock_persists_mutations(tmp_path) -> None:
    storage = Storage(str(tmp_path / "data.json"))

    def mutate(data: dict) -> None:
        data.setdefault("players", {})["123"] = {"user": {"balance": 999}}

    storage.with_lock(mutate)

    assert storage.load()["players"]["123"]["user"]["balance"] == 999
