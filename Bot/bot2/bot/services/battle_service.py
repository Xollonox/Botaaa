"""Battle persistence service for queue/pending invites/active-by-user state."""

from __future__ import annotations

from typing import Any

from bot.data.sqlite_store import SQLiteBattleRepository
from bot.utils.timeutil import now_ts


class BattleService:
    def __init__(self, repo: SQLiteBattleRepository, storage: Any) -> None:
        self.repo = repo
        self.storage = storage

    def bootstrap_from_json(self) -> None:
        if self.repo.json_bootstrap_completed():
            return
        if self.repo.has_persisted_state():
            self.repo.mark_json_bootstrap_completed()
            return
        data = self.storage.load()
        battle = data.get("battle", {})
        if not isinstance(battle, dict):
            battle = {"queue": [], "pending_friendly": {}, "active": {}, "active_by_user": {}}
        self.repo.seed_from_json_battle(battle)
        self.repo.mark_json_bootstrap_completed()

    def hydrate_json_state(self, data: dict[str, Any]) -> dict[str, Any]:
        battle = data.setdefault("battle", {})
        if not isinstance(battle, dict):
            data["battle"] = {"queue": [], "pending_friendly": {}, "active": {}, "active_by_user": {}}
            battle = data["battle"]
        battle["queue"] = self.repo.list_queue(now_ts())
        battle["pending_friendly"] = self.repo.list_pending_friendly(now_ts())
        battle["active_by_user"] = self.repo.list_active_by_user()
        battle.setdefault("active", {})
        return data

    def add_queue_entry(self, user_id: str, joined_at: int, expires_at: int) -> None:
        self.repo.upsert_queue_entry(user_id, joined_at, expires_at)

    def remove_queue_user(self, user_id: str) -> bool:
        return self.repo.remove_queue_user(user_id)

    def remove_queue_users(self, user_ids: list[str]) -> None:
        self.repo.remove_queue_users(user_ids)

    def upsert_pending_friendly(self, target_id: str, payload: dict[str, Any]) -> None:
        self.repo.upsert_pending_friendly(target_id, payload)

    def remove_pending_friendly(self, target_id: str) -> bool:
        return self.repo.remove_pending_friendly(target_id)

    def clear_outgoing_pending(self, challenger_id: str) -> int:
        now = now_ts()
        pending = self.repo.list_pending_friendly(now)
        removed = 0
        for target_id, payload in pending.items():
            if str(payload.get("challenger_id", "")) == str(challenger_id):
                if self.remove_pending_friendly(str(target_id)):
                    removed += 1
        return removed

    def sync_active_by_user_from_data(self, data: dict[str, Any]) -> None:
        battle = data.get("battle", {})
        active_by_user = battle.get("active_by_user", {}) if isinstance(battle, dict) else {}
        if not isinstance(active_by_user, dict):
            active_by_user = {}
        mapping = {str(k): str(v) for k, v in active_by_user.items()}
        self.repo.set_active_by_user(mapping)
