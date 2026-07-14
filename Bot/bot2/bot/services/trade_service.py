"""Trade service backed by SQLite with JSON mirror compatibility."""

from __future__ import annotations

from typing import Any

from bot.data.sqlite_store import SQLiteTradeRepository
from bot.utils.timeutil import now_ts


class TradeService:
    def __init__(self, repo: SQLiteTradeRepository, storage: Any) -> None:
        self.repo = repo
        self.storage = storage

    async def bootstrap_from_json(self) -> None:
        if await self.repo.json_bootstrap_completed():
            return
        if await self.repo.has_persisted_state():
            await self.repo.mark_json_bootstrap_completed()
            return
        data = self.storage.load()
        trades = data.get("trades", {})
        if not isinstance(trades, dict):
            trades = {"pending": {}, "history": []}
        await self.repo.seed_from_json_trades(trades)
        await self.repo.mark_json_bootstrap_completed()

    async def is_pending(self, user_id: str) -> bool:
        return await self.repo.is_pending(user_id)

    async def add_pending_pair(self, a_id: str, b_id: str, *, mirror_json: bool = True) -> bool:
        """Atomically reserve both users as pending.

        Returns True if both were successfully inserted (neither was already
        pending).  Returns False if either was already pending.
        """
        inserted = await self.repo.add_pending_pair(a_id, b_id)
        if not inserted:
            return False
        if mirror_json:
            self.storage.with_lock(
                lambda d: d.setdefault("trades", {}).setdefault("pending", {}).update(
                    {str(a_id): True, str(b_id): True}
                )
            )
        return True

    async def remove_pending(self, user_id: str, *, mirror_json: bool = True) -> bool:
        ok = await self.repo.remove_pending(user_id)
        if ok and mirror_json:
            self.storage.with_lock(lambda d: d.setdefault("trades", {}).setdefault("pending", {}).pop(str(user_id), None))
        return ok

    async def remove_pending_pair(self, a_id: str, b_id: str, *, mirror_json: bool = True) -> None:
        await self.repo.remove_pending_pair(a_id, b_id)
        if not mirror_json:
            return
        self.storage.with_lock(
            lambda d: (
                d.setdefault("trades", {}).setdefault("pending", {}).pop(str(a_id), None),
                d.setdefault("trades", {}).setdefault("pending", {}).pop(str(b_id), None),
            )
        )

    async def clear_pending(self) -> int:
        count = await self.repo.clear_pending()
        self.storage.with_lock(lambda d: d.setdefault("trades", {}).__setitem__("pending", {}))
        return count

    @staticmethod
    def _json_truncate_history(d: dict[str, Any], row: dict[str, Any]) -> None:
        h = d.setdefault("trades", {}).setdefault("history", [])
        h.append(row)
        d["trades"]["history"] = h[-50:]

    async def append_history(self, row: dict[str, Any]) -> None:
        await self.repo.append_history(row)
        self.storage.with_lock(lambda d: self._json_truncate_history(d, row))

    async def history_for_user(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self.repo.recent_history_for_user(user_id, limit=max(1, limit))

    async def hydrate_json_trade_state(self, data: dict[str, Any]) -> dict[str, Any]:
        t = data.setdefault("trades", {})
        if not isinstance(t, dict):
            data["trades"] = {"pending": {}, "history": []}
            t = data["trades"]
        t["pending"] = await self.repo.list_pending()
        return data

    async def post_offer(self, offer_id: str, poster_id: str, poster_name: str, have_card: str, want_card: str, item_uid: str, created_at: int, expires_at: int) -> None:
        await self.repo.post_offer(offer_id, poster_id, poster_name, have_card, want_card, item_uid, created_at, expires_at)

    async def get_open_offers(self, limit: int = 10) -> list[dict[str, Any]]:
        await self.expire_offers()
        return await self.repo.get_open_offers(limit)

    async def cancel_offer(self, offer_id: str, poster_id: str) -> bool:
        return await self.repo.cancel_offer(offer_id, poster_id)

    async def claim_offer(self, offer_id: str) -> dict[str, Any] | None:
        return await self.repo.claim_offer(offer_id, now_ts())

    async def finish_offer(self, offer_id: str, *, accepted: bool) -> bool:
        return await self.repo.finish_offer(offer_id, "accepted" if accepted else "open")

    async def expire_offers(self) -> list[dict[str, Any]]:
        expired = await self.repo.expire_offers(now_ts())
        if not expired:
            return []

        expired_by_owner = {
            (str(row.get("poster_id", "")), str(row.get("item_uid", "")))
            for row in expired
        }

        def unlock(d: dict[str, Any]) -> None:
            players = d.get("players", {})
            if not isinstance(players, dict):
                return
            for owner_id, item_uid in expired_by_owner:
                player = players.get(owner_id, {})
                user = player.get("user", {}) if isinstance(player, dict) else {}
                inventory = user.get("inventory", []) if isinstance(user, dict) else []
                if not isinstance(inventory, list):
                    continue
                for item in inventory:
                    if isinstance(item, dict) and str(item.get("uid", "")) == item_uid:
                        item["trade_locked"] = False
                        break

        self.storage.with_lock(unlock)
        return expired
