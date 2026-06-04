"""Syncs bot data to Supabase so the website can read it."""
from __future__ import annotations
import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://vbvvllaprptilxufsaxv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZidnZsbGFwcnB0aWx4dWZzYXh2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzAzMzgxNCwiZXhwIjoyMDg4NjA5ODE0fQ.ugbaP0kCx1fuPa06bsogD8rjDw9OOoJ2TctTThDUKuI")

_sync_lock = threading.Lock()
_pending   = False

def _do_sync(data: dict[str, Any]) -> None:
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
    """Fire-and-forget sync to Supabase in background thread."""
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
