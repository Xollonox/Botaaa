"""Redeem code logic helpers.

This module intentionally supports both the newer helper signatures and the
older call sites still used by ``bot.features.redeem``. A prior refactor
updated helper APIs without updating every caller, causing runtime TypeErrors.
"""

from __future__ import annotations

import re
from typing import Any

from bot.utils.timeutil import now_ts

CODE_PATTERN = re.compile(r"^[A-Z0-9\-]{4,32}$")


def normalize_code(code: str) -> str:
    """Normalize a redeem code to uppercase stripped form."""
    return str(code).strip().upper()


def validate_code_format(code: str) -> tuple[bool, str]:
    """Validate redeem code format."""
    code = normalize_code(code)
    if not code:
        return False, "Code cannot be empty."
    if not CODE_PATTERN.match(code):
        return False, "Code must be 4-32 characters, uppercase letters, digits, or hyphens."
    return True, "OK"


def is_expired(redeem_entry_or_ts: dict[str, Any] | int | str | None, now: int | None = None) -> bool:
    """Return True if the redeem code has passed its expiry.

    Supports both:
    - ``is_expired(redeem_entry, now)``
    - ``is_expired(expires_at)``
    """
    if now is None:
        now = now_ts()

    if isinstance(redeem_entry_or_ts, dict):
        expires_at = int(redeem_entry_or_ts.get("expires_at", 0))
    else:
        expires_at = int(redeem_entry_or_ts or 0)

    if expires_at == 0:
        return False
    return int(now) > expires_at


def can_use(
    redeem_entry: dict[str, Any],
    user_id: str | None = None,
    player: dict[str, Any] | None = None,
    now: int | None = None,
) -> tuple[bool, str] | bool:
    """Check whether a redeem code can be used.

    Newer callers receive ``(ok, reason)``.
    Legacy callers receive only ``bool``.
    """
    legacy_mode = user_id is None and player is None and now is None
    if now is None:
        now = now_ts()

    if is_expired(redeem_entry, now):
        return False if legacy_mode else (False, "expired")

    max_uses = int(redeem_entry.get("max_uses", 0))
    uses = int(redeem_entry.get("uses", 0))
    if max_uses > 0 and uses >= max_uses:
        return False if legacy_mode else (False, "max_uses_reached")

    if legacy_mode:
        return True

    player = player or {}
    redeemed = player.get("redeemed_codes", {})
    code_key = str(redeem_entry.get("code", ""))
    if isinstance(redeemed, dict) and code_key in redeemed:
        return False, "already_redeemed"

    return True, "ok"


def format_reward(*args: Any) -> str:
    """Format a reward dict for display.

    Supports both ``format_reward(reward)`` and ``format_reward(data, reward)``.
    """
    reward = args[-1] if args else {}
    if not isinstance(reward, dict):
        return "Unknown reward"

    rtype = str(reward.get("type", reward.get("reward_type", ""))).strip().lower()
    rvalue = reward.get("value", reward.get("reward_value", ""))

    if rtype == "coins":
        return f"🪙 {rvalue} coins"
    if rtype in {"premium", "premium_currency", "gems", "gem"}:
        return f"💎 {rvalue} premium"
    if rtype == "card":
        return f"🃏 Card: {rvalue}"
    if rtype == "pack":
        return f"🎴 Pack: {rvalue}"
    return f"{rtype or 'reward'}: {rvalue}"


def list_codes_lines(data: dict[str, Any], now: int | None = None) -> list[str]:
    """Return display lines for all redeem codes."""
    if now is None:
        now = now_ts()

    codes = data.get("redeem_codes", {})
    if not isinstance(codes, dict) or not codes:
        return ["No redeem codes configured."]

    lines = []
    for code_key, entry in codes.items():
        if not isinstance(entry, dict):
            continue
        uses = int(entry.get("uses", 0))
        max_uses = int(entry.get("max_uses", 0))
        expired = is_expired(entry, now)
        status = "❌ Expired" if expired else "✅ Active"
        uses_str = f"{uses}/{max_uses}" if max_uses > 0 else f"{uses}/∞"
        reward_str = format_reward(entry.get("reward", {}))
        lines.append(f"`{code_key}` • {status} • Uses: {uses_str} • Reward: {reward_str}")
    return lines
