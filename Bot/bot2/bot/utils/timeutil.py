"""Time utility helpers."""

from __future__ import annotations

import time


def now_ts() -> int:
    """Return the current Unix timestamp as an integer."""
    return int(time.time())
