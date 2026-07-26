"""Firestore-backed replacement for :class:`bot.data.sqlite_store.SQLiteTradeRepository`.

Preserves the exact async method signatures used by ``TradeService``. The
claim/finish/expire/add-pending-pair compare-and-swap operations that
SQLite implemented with ``BEGIN IMMEDIATE`` are implemented here with
Firestore transactions, which are serializable and auto-retry on
contention — a faithful replacement for the SQL CAS pattern. Filtering and
sorting for offers/history is done client-side to avoid requiring
manually-created Firestore composite indexes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_query import FieldFilter

from .firestore_storage import _sanitize_for_firestore

_MIGRATIONS_COLLECTION = "app_migrations"
_PENDING_COLLECTION = "trade_pending"
_HISTORY_COLLECTION = "trade_history"
_OFFER_COLLECTION = "trade_offer_board"
_HISTORY_LIMIT = 200


class FirestoreTradeRepository:
    JSON_BOOTSTRAP_KEY = "trade_json_bootstrap_v1"

    def __init__(self, client: Client) -> None:
        self._db = client
        self._recover_stale_processing_offers()

    def _recover_stale_processing_offers(self) -> None:
        """A process may die after claiming an offer but before finalizing it.

        Claims are process-local, so make them available again on restart —
        mirrors SQLite's boot-time ``UPDATE ... SET status = 'open' WHERE
        status = 'processing'``.
        """
        coll = self._db.collection(_OFFER_COLLECTION)
        for doc in coll.where(filter=FieldFilter("status", "==", "processing")).stream():
            doc.reference.set({"status": "open"}, merge=True)

    # ------------------------------------------------------------------
    # Sync implementations (private)
    # ------------------------------------------------------------------

    def _migration_done(self, key: str) -> bool:
        return self._db.collection(_MIGRATIONS_COLLECTION).document(key).get().exists

    def _mark_migration_done(self, key: str) -> None:
        self._db.collection(_MIGRATIONS_COLLECTION).document(key).set({"completed_at": int(time.time())})

    def _sync_json_bootstrap_completed(self) -> bool:
        return self._migration_done(self.JSON_BOOTSTRAP_KEY)

    def _sync_mark_json_bootstrap_completed(self) -> None:
        self._mark_migration_done(self.JSON_BOOTSTRAP_KEY)

    def _sync_has_persisted_state(self) -> bool:
        """Return True once trade docs exist in Firestore."""
        pending_any = next(self._db.collection(_PENDING_COLLECTION).limit(1).stream(), None)
        history_any = next(self._db.collection(_HISTORY_COLLECTION).limit(1).stream(), None)
        return pending_any is not None or history_any is not None

    def _sync_seed_from_json_trades(self, trades: dict[str, Any]) -> None:
        pending = trades.get("pending", {}) if isinstance(trades, dict) else {}
        history = trades.get("history", []) if isinstance(trades, dict) else []
        if not isinstance(pending, dict):
            pending = {}
        if not isinstance(history, list):
            history = []

        pending_coll = self._db.collection(_PENDING_COLLECTION)
        for doc in pending_coll.stream():
            doc.reference.delete()
        for uid, active in pending.items():
            if not active:
                continue
            pending_coll.document(str(uid)).set({})

        history_coll = self._db.collection(_HISTORY_COLLECTION)
        for doc in history_coll.stream():
            doc.reference.delete()
        for row in history:
            if not isinstance(row, dict):
                continue
            payload = _sanitize_for_firestore(dict(row))
            payload["a_id"] = str(row.get("a_id", ""))
            payload["b_id"] = str(row.get("b_id", ""))
            payload["resolved_at"] = int(row.get("resolved_at", row.get("created_at", 0)))
            history_coll.add(payload)

    def _sync_is_pending(self, user_id: str) -> bool:
        return self._db.collection(_PENDING_COLLECTION).document(str(user_id)).get().exists

    def _sync_add_pending_pair(self, a_id: str, b_id: str) -> bool:
        """Reserve both users atomically. Returns True only if *both* were newly added."""
        a_ref = self._db.collection(_PENDING_COLLECTION).document(str(a_id))
        b_ref = self._db.collection(_PENDING_COLLECTION).document(str(b_id))

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> bool:
            a_snap = a_ref.get(transaction=transaction)
            b_snap = b_ref.get(transaction=transaction)
            if a_snap.exists or b_snap.exists:
                return False
            transaction.set(a_ref, {})
            transaction.set(b_ref, {})
            return True

        return txn(self._db.transaction())

    def _sync_remove_pending(self, user_id: str) -> bool:
        ref = self._db.collection(_PENDING_COLLECTION).document(str(user_id))
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def _sync_remove_pending_pair(self, a_id: str, b_id: str) -> None:
        self._db.collection(_PENDING_COLLECTION).document(str(a_id)).delete()
        self._db.collection(_PENDING_COLLECTION).document(str(b_id)).delete()

    def _sync_clear_pending(self) -> int:
        coll = self._db.collection(_PENDING_COLLECTION)
        docs = list(coll.stream())
        for doc in docs:
            doc.reference.delete()
        return len(docs)

    def _sync_list_pending(self) -> dict[str, bool]:
        return {doc.id: True for doc in self._db.collection(_PENDING_COLLECTION).stream()}

    def _sync_append_history(self, row: dict[str, Any]) -> None:
        payload = _sanitize_for_firestore(dict(row))
        payload["a_id"] = str(row.get("a_id", ""))
        payload["b_id"] = str(row.get("b_id", ""))
        payload["resolved_at"] = int(row.get("resolved_at", row.get("created_at", 0)))
        coll = self._db.collection(_HISTORY_COLLECTION)
        coll.add(payload)

        # Keep history bounded, dropping the oldest beyond the limit.
        docs = list(coll.order_by("resolved_at", direction=firestore.Query.DESCENDING).stream())
        for doc in docs[_HISTORY_LIMIT:]:
            doc.reference.delete()

    def _sync_recent_history_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        uid = str(user_id)
        coll = self._db.collection(_HISTORY_COLLECTION)
        a_docs = coll.where(filter=FieldFilter("a_id", "==", uid)).stream()
        b_docs = coll.where(filter=FieldFilter("b_id", "==", uid)).stream()
        seen: dict[str, dict[str, Any]] = {}
        for doc in list(a_docs) + list(b_docs):
            seen[doc.id] = doc.to_dict() or {}
        rows = list(seen.values())
        rows.sort(key=lambda r: int(r.get("resolved_at", 0)), reverse=True)
        return rows[:limit]

    def _sync_post_offer(
        self,
        offer_id: str,
        poster_id: str,
        poster_name: str,
        have_card: str,
        want_card: str,
        item_uid: str,
        created_at: int,
        expires_at: int,
    ) -> None:
        self._db.collection(_OFFER_COLLECTION).document(str(offer_id)).set(
            {
                "poster_id": str(poster_id),
                "poster_name": str(poster_name),
                "have_card": str(have_card),
                "want_card": str(want_card),
                "item_uid": str(item_uid),
                "created_at": int(created_at),
                "expires_at": int(expires_at),
                "status": "open",
            }
        )

    def _sync_get_open_offers(self, limit: int = 10) -> list[dict[str, Any]]:
        now = int(time.time())
        rows: list[dict[str, Any]] = []
        query = self._db.collection(_OFFER_COLLECTION).where(filter=FieldFilter("status", "==", "open"))
        for doc in query.stream():
            data = doc.to_dict() or {}
            if int(data.get("expires_at", 0)) > now:
                row = dict(data)
                row["id"] = doc.id
                rows.append(row)
        rows.sort(key=lambda r: int(r.get("created_at", 0)), reverse=True)
        return rows[:limit]

    def _sync_cancel_offer(self, offer_id: str, poster_id: str) -> bool:
        ref = self._db.collection(_OFFER_COLLECTION).document(str(offer_id))

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> bool:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            if data.get("status") != "open" or str(data.get("poster_id")) != str(poster_id):
                return False
            transaction.set(ref, {"status": "cancelled"}, merge=True)
            return True

        return txn(self._db.transaction())

    def _sync_claim_offer(self, offer_id: str, now_ts: int) -> dict[str, Any] | None:
        """Atomically reserve one live offer for a single acceptor."""
        ref = self._db.collection(_OFFER_COLLECTION).document(str(offer_id))

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any] | None:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return None
            data = snap.to_dict() or {}
            if data.get("status") != "open" or int(data.get("expires_at", 0)) <= int(now_ts):
                return None
            transaction.set(ref, {"status": "processing"}, merge=True)
            result = dict(data)
            result["id"] = offer_id
            result["status"] = "processing"
            return result

        return txn(self._db.transaction())

    def _sync_finish_offer(self, offer_id: str, status: str) -> bool:
        if status not in {"accepted", "open"}:
            raise ValueError("Invalid terminal offer status")
        ref = self._db.collection(_OFFER_COLLECTION).document(str(offer_id))

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> bool:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            if data.get("status") != "processing":
                return False
            transaction.set(ref, {"status": status}, merge=True)
            return True

        return txn(self._db.transaction())

    def _sync_expire_offers(self, now_ts: int) -> list[dict[str, Any]]:
        coll = self._db.collection(_OFFER_COLLECTION)
        candidate_refs = []
        query = coll.where(filter=FieldFilter("status", "==", "open"))
        for doc in query.stream():
            data = doc.to_dict() or {}
            if int(data.get("expires_at", 0)) <= int(now_ts):
                candidate_refs.append(doc.reference)

        expired: list[dict[str, Any]] = []
        for ref in candidate_refs:
            @firestore.transactional
            def txn(transaction: firestore.Transaction, ref=ref) -> dict[str, Any] | None:
                snap = ref.get(transaction=transaction)
                if not snap.exists:
                    return None
                data = snap.to_dict() or {}
                if data.get("status") != "open" or int(data.get("expires_at", 0)) > int(now_ts):
                    return None
                transaction.set(ref, {"status": "expired"}, merge=True)
                result = dict(data)
                result["id"] = ref.id
                result["status"] = "expired"
                return result

            row = txn(self._db.transaction())
            if row is not None:
                expired.append(row)
        return expired

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def json_bootstrap_completed(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_json_bootstrap_completed)

    async def mark_json_bootstrap_completed(self) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_mark_json_bootstrap_completed)

    async def has_persisted_state(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_has_persisted_state)

    async def seed_from_json_trades(self, trades: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_seed_from_json_trades, trades)

    async def is_pending(self, user_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_is_pending, user_id)

    async def add_pending_pair(self, a_id: str, b_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_add_pending_pair, a_id, b_id)

    async def remove_pending(self, user_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_remove_pending, user_id)

    async def remove_pending_pair(self, a_id: str, b_id: str) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_remove_pending_pair, a_id, b_id)

    async def clear_pending(self) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_clear_pending)

    async def list_pending(self) -> dict[str, bool]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_pending)

    async def append_history(self, row: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_append_history, row)

    async def recent_history_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_recent_history_for_user, user_id, limit)

    async def post_offer(
        self,
        offer_id: str,
        poster_id: str,
        poster_name: str,
        have_card: str,
        want_card: str,
        item_uid: str,
        created_at: int,
        expires_at: int,
    ) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._sync_post_offer,
            offer_id,
            poster_id,
            poster_name,
            have_card,
            want_card,
            item_uid,
            created_at,
            expires_at,
        )

    async def get_open_offers(self, limit: int = 10) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_get_open_offers, limit)

    async def cancel_offer(self, offer_id: str, poster_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_cancel_offer, offer_id, poster_id)

    async def claim_offer(self, offer_id: str, now_ts: int) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_claim_offer, offer_id, now_ts)

    async def finish_offer(self, offer_id: str, status: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_finish_offer, offer_id, status)

    async def expire_offers(self, now_ts: int) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_expire_offers, now_ts)
