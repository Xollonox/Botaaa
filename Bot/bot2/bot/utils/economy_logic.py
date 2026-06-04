"""Economy helper functions for balances and cooldowns."""

from __future__ import annotations

from typing import Any


def add_balance(user: dict[str, Any], amount: int) -> int:
    """Add *amount* coins to *user* and return the new balance."""
    current = int(user.get("balance", 0))
    new = current + int(amount)
    user["balance"] = new
    return new


def add_premium(user: dict[str, Any], amount: int) -> int:
    """Add *amount* premium currency to *user* and return the new balance."""
    current = int(user.get("premium_balance", 0))
    new = current + int(amount)
    user["premium_balance"] = new
    return new


def deduct_balance(user: dict[str, Any], amount: int) -> tuple[bool, int]:
    """
    Deduct *amount* from *user* balance if sufficient funds exist.

    Returns (success, new_balance).
    """
    current = int(user.get("balance", 0))
    if current < int(amount):
        return False, current
    new = current - int(amount)
    user["balance"] = new
    return True, new


def cooldown_remaining(last_ts: int, cooldown_seconds: int, now: int) -> int:
    """Return seconds remaining on a cooldown, or 0 if cooldown has expired."""
    elapsed = now - last_ts
    remaining = cooldown_seconds - elapsed
    return max(0, remaining)


def fmt_duration(seconds: int) -> str:
    """Format a duration in seconds to a human-readable string."""
    seconds = int(seconds)
    if seconds <= 0:
        return "Ready"

    parts = []
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    secs = seconds % 60

    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not days:
        parts.append(f"{secs}s")

    return " ".join(parts) if parts else "< 1s"
