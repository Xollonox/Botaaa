"""Trade service backed by SQLite with JSON mirror compatibility."""

from __future__ import annotations

from typing import Any

from bot.data.sqlite_store import SQLiteTradeRepository


class TradeService:
    def __init__(self, repo: SQLiteTradeRepository, storage: Any) -> None:
        self.repo = repo
        self.storage = storage

    def bootstrap_from_json(self) -> None:
        if self.repo.json_bootstrap_completed():
            return
        if self.repo.has_persisted_state():
            self.repo.mark_json_bootstrap_completed()
            return
        data = self.storage.load()
        trades = data.get("trades", {})
        if not isinstance(trades, dict):
            trades = {"pending": {}, "history": []}
        self.repo.seed_from_json_trades(trades)
        self.repo.mark_json_bootstrap_completed()

    def is_pending(self, user_id: str) -> bool:
        return self.repo.is_pending(user_id)

    def add_pending_pair(self, a_id: str, b_id: str, *, mirror_json: bool = True) -> None:
        self.repo.add_pending_pair(a_id, b_id)
        if not mirror_json:
            return
        self.storage.with_lock(
            lambda d: d.setdefault("trades", {}).setdefault("pending", {}).update({str(a_id): True, str(b_id): True})
        )

    def remove_pending(self, user_id: str, *, mirror_json: bool = True) -> bool:
        ok = self.repo.remove_pending(user_id)
        if ok and mirror_json:
            self.storage.with_lock(lambda d: d.setdefault("trades", {}).setdefault("pending", {}).pop(str(user_id), None))
        return ok

    def remove_pending_pair(self, a_id: str, b_id: str, *, mirror_json: bool = True) -> None:
        self.repo.remove_pending_pair(a_id, b_id)
        if not mirror_json:
            return
        self.storage.with_lock(
            lambda d: (
                d.setdefault("trades", {}).setdefault("pending", {}).pop(str(a_id), None),
                d.setdefault("trades", {}).setdefault("pending", {}).pop(str(b_id), None),
            )
        )

    @staticmethod
    def _json_truncate_history(d: dict[str, Any], row: dict[str, Any]) -> None:
        h = d.setdefault("trades", {}).setdefault("history", [])
        h.append(row)
        d["trades"]["history"] = h[-50:]

    def append_history(self, row: dict[str, Any]) -> None:
        self.repo.append_history(row)
        self.storage.with_lock(lambda d: self._json_truncate_history(d, row))

    def history_for_user(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.recent_history_for_user(user_id, limit=max(1, limit))

    def hydrate_json_trade_state(self, data: dict[str, Any]) -> dict[str, Any]:
        t = data.setdefault("trades", {})
        if not isinstance(t, dict):
            data["trades"] = {"pending": {}, "history": []}
            t = data["trades"]
        t["pending"] = self.repo.list_pending()
        return data
