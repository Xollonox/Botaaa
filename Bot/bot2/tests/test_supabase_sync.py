from __future__ import annotations

import threading
import time

from bot.data import supabase_sync


def test_sync_async_coalesces_to_latest_snapshot(monkeypatch) -> None:
    calls: list[int] = []
    first_started = threading.Event()
    release_first = threading.Event()

    def fake_do_sync(data: dict) -> None:
        calls.append(int(data["n"]))
        if int(data["n"]) == 1:
            first_started.set()
            release_first.wait(1)

    monkeypatch.setattr(supabase_sync, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "secret")
    monkeypatch.setattr(supabase_sync, "_do_sync", fake_do_sync)
    monkeypatch.setattr(supabase_sync, "SUPABASE_SYNC_INTERVAL", 0.0)  # disable debounce sleep in tests
    monkeypatch.setattr(supabase_sync, "_pending", False)
    monkeypatch.setattr(supabase_sync, "_latest_data", None)

    supabase_sync.sync_async({"n": 1})
    assert first_started.wait(1)

    supabase_sync.sync_async({"n": 2})
    supabase_sync.sync_async({"n": 3})
    release_first.set()

    deadline = time.time() + 1
    while time.time() < deadline and calls != [1, 3]:
        time.sleep(0.01)

    assert calls == [1, 3]
    assert supabase_sync._pending is False
    assert supabase_sync._latest_data is None

