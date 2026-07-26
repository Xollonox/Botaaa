"""Firestore-backed replacement for the JSON ``Storage`` class.

Preserves the exact public API of :class:`bot.data.storage.Storage`
(``load``, ``load_readonly``, ``with_lock``, ``save``, ``async_save``) so
every existing call site (``self.bot.storage.with_lock(lambda data: ...)``)
keeps working unmodified. Only the backing store changes: instead of a
single JSON file, data is split between a ``players`` collection (one
document per user id, to stay well under Firestore's 1MB/document limit)
and a single ``bot_state/global`` document holding everything else
(cards, weapons, keystones, season, gangs, server_settings, ai, ...).

``with_lock``/``save`` remain synchronous, blocking network calls to
Firestore for the duration — this matches the original synchronous
``Storage.with_lock`` contract that ~60+ call sites rely on (none of them
``await`` it). This is a deliberate interface-parity tradeoff.
"""

from __future__ import annotations

import logging
import threading
from copy import deepcopy
from typing import Any, Callable, TypeVar

from google.cloud.firestore_v1 import Client

from .defaults import build_default_data, ensure_structure

T = TypeVar("T")
logger = logging.getLogger(__name__)

PLAYERS_COLLECTION = "players"
GLOBAL_COLLECTION = "bot_state"
GLOBAL_DOC_ID = "global"

# Firestore batched writes are capped at 500 operations.
_BATCH_LIMIT = 400


def _sanitize_for_firestore(value: Any, path: str = "root") -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_for_firestore(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_firestore(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, tuple):
        logger.warning("[FIRESTORE_SANITIZE] Converted tuple at path %s to list (len=%s)", path, len(value))
        return [_sanitize_for_firestore(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, set):
        sample = next(iter(value), None)
        logger.warning("[FIRESTORE_SANITIZE] Converted set at path %s to list (len=%s sample=%r)", path, len(value), sample)
        normalized = sorted(str(x) for x in value)
        return [_sanitize_for_firestore(v, f"{path}[{i}]") for i, v in enumerate(normalized)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    logger.warning("[FIRESTORE_SANITIZE] Converted unsupported type at path %s type=%s to str", path, type(value).__name__)
    return str(value)


class FirestoreStorage:
    """Thread-safe Firestore-backed storage matching ``Storage``'s public API."""

    def __init__(self, client: Client) -> None:
        self._db = client
        self.lock = threading.Lock()
        self._cache: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    def _fetch_global(self) -> dict[str, Any]:
        doc = self._db.collection(GLOBAL_COLLECTION).document(GLOBAL_DOC_ID).get()
        data = doc.to_dict()
        return data if isinstance(data, dict) else {}

    def _fetch_players(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for doc in self._db.collection(PLAYERS_COLLECTION).stream():
            data = doc.to_dict()
            if isinstance(data, dict):
                out[doc.id] = data
        return out

    def _load_from_firestore(self) -> dict[str, Any]:
        global_data = self._fetch_global()
        players = self._fetch_players()
        if not global_data and not players:
            data = build_default_data()
            self._write_full(data)
            return data
        combined = {**global_data, "players": players}
        return ensure_structure(combined)

    def _live_data(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = self._load_from_firestore()
        return self._cache

    # ------------------------------------------------------------------
    # Public API (mirrors bot.data.storage.Storage)
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        return deepcopy(self._live_data())

    def load_readonly(self) -> dict[str, Any]:
        return self._live_data()

    def _write_full(self, data: dict[str, Any]) -> None:
        """Full replace: used only for first-time seeding of an empty database."""
        sanitized = _sanitize_for_firestore(data)
        players = sanitized.pop("players", {}) if isinstance(sanitized.get("players"), dict) else {}
        self._db.collection(GLOBAL_COLLECTION).document(GLOBAL_DOC_ID).set(sanitized)
        items = list(players.items())
        coll = self._db.collection(PLAYERS_COLLECTION)
        for i in range(0, len(items), _BATCH_LIMIT):
            batch = self._db.batch()
            for uid, pdata in items[i : i + _BATCH_LIMIT]:
                batch.set(coll.document(str(uid)), pdata)
            batch.commit()

    def _commit_diff(self, data: dict[str, Any], before: dict[str, Any]) -> None:
        """Write only the top-level keys / player docs that actually changed."""
        sanitized = _sanitize_for_firestore(data)
        players = sanitized.get("players", {}) if isinstance(sanitized.get("players"), dict) else {}
        rest = {k: v for k, v in sanitized.items() if k != "players"}

        before_players = before.get("players", {}) if isinstance(before.get("players"), dict) else {}
        before_rest = {k: v for k, v in before.items() if k != "players"}

        coll = self._db.collection(PLAYERS_COLLECTION)
        ops: list[tuple[str, str, Any]] = []  # (kind, doc_id, payload)
        for uid, pdata in players.items():
            if pdata != before_players.get(uid):
                ops.append(("set", str(uid), pdata))
        for uid in before_players.keys() - players.keys():
            ops.append(("delete", str(uid), None))

        rest_changed = rest != before_rest

        if not ops and not rest_changed:
            return

        for i in range(0, len(ops), _BATCH_LIMIT):
            batch = self._db.batch()
            chunk = ops[i : i + _BATCH_LIMIT]
            for kind, uid, payload in chunk:
                if kind == "set":
                    batch.set(coll.document(uid), payload)
                else:
                    batch.delete(coll.document(uid))
            if rest_changed and i == 0:
                batch.set(self._db.collection(GLOBAL_COLLECTION).document(GLOBAL_DOC_ID), rest)
            batch.commit()

        if rest_changed and not ops:
            self._db.collection(GLOBAL_COLLECTION).document(GLOBAL_DOC_ID).set(rest)

    def save(self, data: dict[str, Any]) -> None:
        """Persist *data*, diffing against the current cache to minimize writes."""
        before = self._cache if self._cache is not None else self._load_from_firestore()
        self._commit_diff(data, before)
        self._cache = data

    async def async_save(self, data: dict[str, Any]) -> None:
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.save, data)

    def with_lock(self, fn: Callable[[dict[str, Any]], T]) -> T:
        """Execute *fn* with exclusive access to the storage.

        Blocking network I/O to Firestore happens inside this call, matching
        the original ``Storage.with_lock`` contract (called synchronously,
        without ``await``, from ~60+ existing call sites).
        """
        with self.lock:
            data = deepcopy(self._live_data())
            before = deepcopy(data)
            result = fn(data)
            self._commit_diff(data, before)
            self._cache = data
            return result
