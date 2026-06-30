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


def test_with_lock_does_not_poison_cache_when_save_fails(tmp_path, monkeypatch) -> None:
    storage = Storage(str(tmp_path / "data.json"))
    storage.with_lock(lambda data: data.setdefault("players", {}))

    original_replace = __import__("os").replace

    def fail_replace(src: str, dst: str) -> None:
        raise OSError("disk write failed")

    monkeypatch.setattr("os.replace", fail_replace)
    try:
        try:
            storage.with_lock(
                lambda data: data.setdefault("players", {}).setdefault(
                    "123", {"user": {"balance": 999}}
                )
            )
        except OSError:
            pass
    finally:
        monkeypatch.setattr("os.replace", original_replace)

    assert "123" not in storage.load().get("players", {})
