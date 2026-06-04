"""Generic reward granting logic."""

from __future__ import annotations

from typing import Any


def grant_reward(
    data: dict[str, Any],
    user_id: str,
    reward: dict[str, Any],
    now: int = 0,
) -> tuple[bool, str]:
    """
    Grant a reward to *user_id* based on *reward* dict.

    reward format: {"reward_type": "coins"|"premium"|"card", "reward_value": ...}

    Returns (success, message).
    """
    players = data.get("players", {})
    player = players.get(str(user_id)) if isinstance(players, dict) else None
    if not isinstance(player, dict):
        return False, "player_not_found"

    user = player.get("user", {})
    if not isinstance(user, dict):
        return False, "player_data_invalid"

    reward_type = str(reward.get("reward_type", ""))
    reward_value = reward.get("reward_value")

    if reward_type == "coins":
        amount = int(reward_value or 0)
        if amount <= 0:
            return False, "invalid_amount"
        from bot.utils.economy_logic import add_balance
        add_balance(user, amount)
        return True, f"Granted {amount} coins."

    elif reward_type == "premium":
        amount = int(reward_value or 0)
        if amount <= 0:
            return False, "invalid_amount"
        from bot.utils.economy_logic import add_premium
        add_premium(user, amount)
        return True, f"Granted {amount} premium currency."

    elif reward_type == "card":
        card_name = str(reward_value or "").strip()
        if not card_name:
            return False, "no_card_name"
        catalog = data.get("cards", {})
        card_def = catalog.get(card_name) if isinstance(catalog, dict) else None
        if not isinstance(card_def, dict):
            return False, f"Card '{card_name}' not found in catalog."
        from bot.utils.inventory_api import add_card_instance_from_def
        add_card_instance_from_def(user, card_def, acquired_at=now)
        return True, f"Granted card '{card_name}'."

    elif reward_type == "pack":
        pack_key = str(reward_value or "").strip()
        if not pack_key:
            return False, "no_pack_key"
        owned_packs = user.setdefault("owned_packs", {})
        if not isinstance(owned_packs, dict):
            user["owned_packs"] = {}
            owned_packs = user["owned_packs"]
        owned_packs[pack_key] = int(owned_packs.get(pack_key, 0)) + 1
        return True, f"Granted pack '{pack_key}'."

    else:
        return False, f"Unknown reward_type '{reward_type}'."
