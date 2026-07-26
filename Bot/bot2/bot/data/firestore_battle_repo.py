"""Firestore-backed replacement for :class:`bot.data.sqlite_store.SQLiteBattleRepository`.

Preserves the exact async method signatures used by ``BattleService``.
Backing collections: ``battle_queue`` (one doc per queued user),
``battle_pending_friendly`` (one doc per pending friendly-battle target),
``battle_active_by_user`` (one doc per user with an active battle). None of
these need compare-and-swap in the original SQLite implementation either,
so this is plain CRUD.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google.cloud.firestore_v1 import Client

from .firestore_storage import _sanitize_for_firestore

_MIGRATIONS_COLLECTION = "app_migrations"
_QUEUE_COLLECTION = "battle_queue"
_PENDING_FRIENDLY_COLLECTION = "battle_pending_friendly"
_ACTIVE_BY_USER_COLLECTION = "battle_active_by_user"


class FirestoreBattleRepository:
    JSON_BOOTSTRAP_KEY = "battle_json_bootstrap_v1"

    def __init__(self, client: Client) -> None:
        self._db = client

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
        """Return True once battle docs exist in Firestore."""
        for coll_name in (_QUEUE_COLLECTION, _PENDING_FRIENDLY_COLLECTION, _ACTIVE_BY_USER_COLLECTION):
            if next(self._db.collection(coll_name).limit(1).stream(), None) is not None:
                return True
        return False

    def _sync_seed_from_json_battle(self, battle: dict[str, Any]) -> None:
        queue = battle.get("queue", []) if isinstance(battle, dict) else []
        pending = battle.get("pending_friendly", {}) if isinstance(battle, dict) else {}
        active_by_user = battle.get("active_by_user", {}) if isinstance(battle, dict) else {}
        if not isinstance(queue, list):
            queue = []
        if not isinstance(pending, dict):
            pending = {}
        if not isinstance(active_by_user, dict):
            active_by_user = {}

        queue_coll = self._db.collection(_QUEUE_COLLECTION)
        for doc in queue_coll.stream():
            doc.reference.delete()
        for q in queue:
            if not isinstance(q, dict):
                continue
            queue_coll.document(str(q.get("user_id", ""))).set(
                {"joined_at": int(q.get("joined_at", 0)), "expires_at": int(q.get("expires_at", 0))}
            )

        pending_coll = self._db.collection(_PENDING_FRIENDLY_COLLECTION)
        for doc in pending_coll.stream():
            doc.reference.delete()
        for target_id, payload in pending.items():
            if not isinstance(payload, dict):
                continue
            pending_coll.document(str(target_id)).set(_sanitize_for_firestore(dict(payload)))

        active_coll = self._db.collection(_ACTIVE_BY_USER_COLLECTION)
        for doc in active_coll.stream():
            doc.reference.delete()
        for uid, bid in active_by_user.items():
            active_coll.document(str(uid)).set({"battle_id": str(bid)})

    def _sync_list_queue(self, now_ts: int) -> list[dict[str, Any]]:
        coll = self._db.collection(_QUEUE_COLLECTION)
        rows: list[dict[str, Any]] = []
        for doc in coll.stream():
            data = doc.to_dict() or {}
            if int(data.get("expires_at", 0)) <= int(now_ts):
                doc.reference.delete()
                continue
            rows.append(
                {
                    "user_id": doc.id,
                    "joined_at": int(data.get("joined_at", 0)),
                    "expires_at": int(data.get("expires_at", 0)),
                }
            )
        rows.sort(key=lambda r: r["joined_at"])
        return rows

    def _sync_upsert_queue_entry(self, user_id: str, joined_at: int, expires_at: int) -> None:
        self._db.collection(_QUEUE_COLLECTION).document(str(user_id)).set(
            {"joined_at": int(joined_at), "expires_at": int(expires_at)}
        )

    def _sync_remove_queue_user(self, user_id: str) -> bool:
        ref = self._db.collection(_QUEUE_COLLECTION).document(str(user_id))
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def _sync_remove_queue_users(self, user_ids: list[str]) -> None:
        if not user_ids:
            return
        batch = self._db.batch()
        for uid in user_ids:
            batch.delete(self._db.collection(_QUEUE_COLLECTION).document(str(uid)))
        batch.commit()

    def _sync_list_pending_friendly(self, now_ts: int) -> dict[str, dict[str, Any]]:
        coll = self._db.collection(_PENDING_FRIENDLY_COLLECTION)
        out: dict[str, dict[str, Any]] = {}
        for doc in coll.stream():
            data = doc.to_dict() or {}
            if int(data.get("expires_at", 0)) <= int(now_ts):
                doc.reference.delete()
                continue
            out[doc.id] = data
        return out

    def _sync_upsert_pending_friendly(self, target_id: str, payload: dict[str, Any]) -> None:
        self._db.collection(_PENDING_FRIENDLY_COLLECTION).document(str(target_id)).set(
            _sanitize_for_firestore(dict(payload))
        )

    def _sync_remove_pending_friendly(self, target_id: str) -> bool:
        ref = self._db.collection(_PENDING_FRIENDLY_COLLECTION).document(str(target_id))
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def _sync_list_active_by_user(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for doc in self._db.collection(_ACTIVE_BY_USER_COLLECTION).stream():
            data = doc.to_dict() or {}
            out[doc.id] = str(data.get("battle_id", ""))
        return out

    def _sync_set_active_by_user(self, mapping: dict[str, str]) -> None:
        coll = self._db.collection(_ACTIVE_BY_USER_COLLECTION)
        for doc in coll.stream():
            doc.reference.delete()
        for uid, bid in mapping.items():
            coll.document(str(uid)).set({"battle_id": str(bid)})

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

    async def seed_from_json_battle(self, battle: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_seed_from_json_battle, battle)

    async def list_queue(self, now_ts: int) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_queue, now_ts)

    async def upsert_queue_entry(self, user_id: str, joined_at: int, expires_at: int) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_upsert_queue_entry, user_id, joined_at, expires_at)

    async def remove_queue_user(self, user_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_remove_queue_user, user_id)

    async def remove_queue_users(self, user_ids: list[str]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_remove_queue_users, user_ids)

    async def list_pending_friendly(self, now_ts: int) -> dict[str, dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_pending_friendly, now_ts)

    async def upsert_pending_friendly(self, target_id: str, payload: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_upsert_pending_friendly, target_id, payload)

    async def remove_pending_friendly(self, target_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_remove_pending_friendly, target_id)

    async def list_active_by_user(self) -> dict[str, str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_active_by_user)

    async def set_active_by_user(self, mapping: dict[str, str]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_set_active_by_user, mapping)
