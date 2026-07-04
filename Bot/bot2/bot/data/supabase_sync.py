"""Sync bot data to Supabase so the website can read it.

Storage.save() calls sync_async(data) after successful local writes. The sync is
a no-op unless SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are configured.
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
# Minimum seconds between successive POSTs.  Override with SUPABASE_SYNC_INTERVAL.
SUPABASE_SYNC_INTERVAL: float = float(os.getenv("SUPABASE_SYNC_INTERVAL", "5.0"))

_sync_lock = threading.Lock()
_pending = False
_latest_data: dict[str, Any] | None = None


def _do_sync(data: dict[str, Any]) -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.debug("Supabase sync skipped: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured.")
        return
    try:
        import urllib.request
        payload = json.dumps({"id": "main", "data": data}).encode()
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/bot_data",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Prefer": "resolution=merge-duplicates",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except (OSError, ValueError, TypeError):
        # OSError covers urllib.error.URLError / HTTPError / socket.timeout (all subclass OSError).
        # ValueError covers malformed URL schemes; TypeError covers json.dumps failures.
        logger.exception("Supabase sync failed")


def sync_async(data: dict[str, Any]) -> None:
    """Fire-and-forget sync to Supabase in a background thread.

    If writes arrive while a sync is already running, only the newest snapshot
    is retained and synced after the active request finishes.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    global _latest_data, _pending
    with _sync_lock:
        _latest_data = data
        if _pending:
            return
        _pending = True

    def run() -> None:
        global _latest_data, _pending
        while True:
            with _sync_lock:
                current = _latest_data
                _latest_data = None
            if current is None:
                with _sync_lock:
                    if _latest_data is None:
                        _pending = False
                        return
                    continue
            _do_sync(current)
            # Debounce: sleep for the configured interval so that a burst of
            # save() calls in the next SUPABASE_SYNC_INTERVAL seconds is
            # coalesced into one POST rather than one POST per call.
            # Any snapshot written to _latest_data while we sleep will be
            # picked up on the next loop iteration (newest-wins).
            interval = SUPABASE_SYNC_INTERVAL
            if interval > 0:
                time.sleep(interval)

    threading.Thread(target=run, daemon=True).start()
