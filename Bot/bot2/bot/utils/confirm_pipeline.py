"""Confirm-action pipeline helpers."""

from __future__ import annotations

from typing import Any

CONFIRM_TTL = 300  # 5 minutes


def pop_and_validate_action(
    data: dict[str, Any],
    owner_id: str,
    action_id: str,
    now: int,
) -> tuple[bool, str | dict[str, Any]]:
    """
    Pop and validate a pending confirm action.

    Returns (True, action_dict) on success, or (False, error_string) on failure.
    """
    confirm_actions = data.get("confirm_actions", {})
    if not isinstance(confirm_actions, dict):
        return False, "no_pending_actions"

    action = confirm_actions.get(str(action_id))
    if not isinstance(action, dict):
        return False, "action_not_found"

    if str(action.get("owner_id", "")) != str(owner_id):
        return False, "not_your_action"

    created_at = int(action.get("created_at", 0))
    if (now - created_at) > CONFIRM_TTL:
        confirm_actions.pop(str(action_id), None)
        return False, "action_expired"

    # Pop the action
    confirm_actions.pop(str(action_id), None)
    return True, action


def stage_action(
    data: dict[str, Any],
    owner_id: str,
    action_id: str,
    action_type: str,
    payload: dict[str, Any],
    now: int,
) -> None:
    """Stage a confirm action in *data*."""
    confirm_actions = data.setdefault("confirm_actions", {})
    if not isinstance(confirm_actions, dict):
        confirm_actions = {}
        data["confirm_actions"] = confirm_actions
    confirm_actions[str(action_id)] = {
        "owner_id": str(owner_id),
        "action_id": str(action_id),
        "action_type": str(action_type),
        "payload": payload,
        "created_at": int(now),
    }
