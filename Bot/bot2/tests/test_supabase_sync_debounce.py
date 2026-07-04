"""Debounce/coalescing tests for supabase_sync.sync_async.

Rapid successive sync_async() calls must collapse into far fewer network POSTs
than there were calls.  Two behaviours we want to lock in:

1. With the default 5s SUPABASE_SYNC_INTERVAL, a burst of N calls inside 1s
   produces exactly ONE POST inside a 5s window (nothing else has time to
   fire because the worker sleeps ``interval`` between flushes).

2. With a small interval (0.1s), a burst of N calls still coalesces to at
   most 2 POSTs — the first snapshot plus one final flush of the latest
   snapshot — not N.

Both mock ``urllib.request.urlopen`` so no real network I/O happens.
"""

from __future__ import annotations

import threading
import time
import urllib.request

from bot.data import supabase_sync


class _FakeResp:
    def read(self) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


def _reset_module() -> None:
    with supabase_sync._sync_lock:
        supabase_sync._pending = False
        supabase_sync._latest_data = None


def test_burst_coalesces_to_single_post_within_5s_window(monkeypatch) -> None:
    """Default 5s interval: 20 rapid calls → 1 POST inside a 5s window."""
    monkeypatch.setattr(supabase_sync, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "secret")
    monkeypatch.setattr(supabase_sync, "SUPABASE_SYNC_INTERVAL", 5.0)
    _reset_module()

    posts: list[str] = []
    lock = threading.Lock()

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        with lock:
            posts.append(req.full_url)
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    for i in range(20):
        supabase_sync.sync_async({"n": i})
    # All 20 calls return in <<1s; the worker's first POST fires nearly
    # immediately, but the second is gated by a 5s time.sleep inside the
    # worker loop, so nothing else can fire in the ~1s window we sample.
    time.sleep(1.0)
    assert len(posts) == 1, f"expected exactly 1 POST inside 5s window, got {len(posts)}"

    _reset_module()


def test_burst_coalesces_to_at_most_two_posts_with_small_interval(monkeypatch) -> None:
    """Small interval: N rapid calls → at most 2 POSTs (first + coalesced final)."""
    monkeypatch.setattr(supabase_sync, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "secret")
    monkeypatch.setattr(supabase_sync, "SUPABASE_SYNC_INTERVAL", 0.1)
    _reset_module()

    posts: list[dict] = []
    lock = threading.Lock()

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        with lock:
            posts.append({"url": req.full_url})
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    N = 30
    for i in range(N):
        supabase_sync.sync_async({"n": i})

    # Give the worker time to flush the coalesced tail: two intervals + slack.
    deadline = time.time() + 3
    while time.time() < deadline:
        with supabase_sync._sync_lock:
            if not supabase_sync._pending and supabase_sync._latest_data is None:
                break
        time.sleep(0.05)

    assert 1 <= len(posts) <= 2, (
        f"N={N} calls should coalesce to 1-2 POSTs, got {len(posts)}"
    )

    _reset_module()
