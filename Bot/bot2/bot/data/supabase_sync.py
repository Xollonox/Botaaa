"""Syncs bot data to Supabase so the website can read it.

NOTE: This module is not currently wired into the main application.
To enable Supabase sync, call sync_async(data) after storage writes
and set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY environment variables.
"""
from __future__ import annotations
import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_sync_lock = threading.Lock()
_pending   = False


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
    except Exception as e:
        logger.warning("Supabase sync failed: %s", e)


def sync_async(data: dict[str, Any]) -> None:
    """Fire-and-forget sync to Supabase in background thread.

    No-op if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY are not configured.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    global _pending
    with _sync_lock:
        if _pending:
            return
        _pending = True

    def run() -> None:
        global _pending
        try:
            _do_sync(data)
        finally:
            with _sync_lock:
                _pending = False

    threading.Thread(target=run, daemon=True).start()
