"""Thread-safe JSON storage with atomic writes."""

from __future__ import annotations

import json
import logging
import asyncio
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, TypeVar

from .defaults import build_default_data, ensure_structure

T = TypeVar("T")
logger = logging.getLogger(__name__)


def _sanitize_for_json(value: Any, path: str = "root") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            out[key] = _sanitize_for_json(v, f"{path}.{key}")
        return out
    if isinstance(value, list):
        return [_sanitize_for_json(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, tuple):
        logger.warning("[STORAGE_SANITIZE] Converted tuple at path %s to list (len=%s)", path, len(value))
        return [_sanitize_for_json(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, set):
        sample = next(iter(value), None)
        logger.warning("[STORAGE_SANITIZE] Converted set at path %s to list (len=%s sample=%r)", path, len(value), sample)
        normalized = sorted([str(x) for x in value])
        return [_sanitize_for_json(v, f"{path}[{i}]") for i, v in enumerate(normalized)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    logger.warning("[STORAGE_SANITIZE] Converted unsupported type at path %s type=%s to str", path, type(value).__name__)
    return str(value)


class Storage:
    """Thread‑safe JSON storage with in‑memory caching.

    The original implementation read the JSON file on every ``load`` call,
    which caused a noticeable I/O overhead for commands that only needed to read
    data (e.g. the global terms gate).  This version caches the parsed JSON in
    ``self._cache`` after the first successful load and updates the cache on each
    ``save``.  Reads return a defensive snapshot, while writes continue to hold
    ``self.lock`` to ensure atomic file writes.
    """
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        # ``threading.Lock`` is kept because the bot runs in a single asyncio
        # thread; the lock protects the file-write sequence and guarantees the
        # cache remains consistent between concurrent ``with_lock`` calls.
        self.lock = threading.Lock()
        # In‑memory cache – ``None`` means the file has not been loaded yet.
        self._cache: dict[str, Any] | None = None

    def _live_data(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = self._load_from_disk()
        return self._cache

    def _load_from_disk(self) -> dict[str, Any]:
        """Read the JSON file from disk, handling corruption.

        This helper is used when the cache is empty or when the file needs to be
        reparsed after a failure.
        """
        if not self.path.exists():
            data = build_default_data()
            self.save(data)
            return data
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._backup_corrupt_file()
            data = build_default_data()
            self.save(data)
            return data
        return ensure_structure(data)

    def load(self) -> dict[str, Any]:
        """Return a snapshot of the current data.

        Mutations must go through ``with_lock`` so they are persisted atomically.
        """
        return deepcopy(self._live_data())

    def load_readonly(self) -> dict[str, Any]:
        """Return the raw cached dict WITHOUT deepcopy.

        Fast-path read for hot code that only inspects the data. Callers MUST
        NOT mutate the returned dict (or any nested structure); doing so would
        corrupt the in-memory cache and bypass the atomic-write path. Use
        :meth:`load` or :meth:`with_lock` for any code that may mutate.
        """
        return self._live_data()

    def _write_to_disk(self, data: dict[str, Any]) -> None:
        """Sanitize *data* and write it atomically to ``self.path``.

        Extracted so both the sync :meth:`save` and the async
        :meth:`async_save` paths share the identical write body.
        """
        sanitized = _sanitize_for_json(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(sanitized, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.path)

    def save(self, data: dict[str, Any]) -> None:
        """Write *data* to disk and refresh the in‑memory cache.

        ``data`` is expected to be the same instance returned by ``load`` (or a
        copy that the caller wants to persist).  The method sanitises the payload,
        writes it atomically, and then stores the reference in ``self._cache``.

        The cache is updated after the atomic write succeeds. The write stays
        synchronous so two consecutive saves cannot reach disk out of order.
        """
        self._write_to_disk(data)
        self._cache = data
        try:
            from .supabase_sync import sync_async

            sync_async(deepcopy(self._cache))
        except Exception:
            logger.exception("Failed to schedule Supabase sync for %s", self.path)

    async def async_save(self, data: dict[str, Any]) -> None:
        """Async variant of :meth:`save` that offloads the disk write.

        The JSON serialization + fsync are pushed to the default executor so
        the event loop is not blocked. The in-memory cache and Supabase sync
        happen back on the loop thread after the write completes.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._write_to_disk, data)
        self._cache = data
        try:
            from .supabase_sync import sync_async

            sync_async(deepcopy(self._cache))
        except Exception:
            logger.exception("Failed to schedule Supabase sync for %s", self.path)

    def with_lock(self, fn: Callable[[dict[str, Any]], T]) -> T:
        """Execute *fn* with exclusive access to the storage.

        ``fn`` receives a writable snapshot, may modify it, and its return value
        is propagated back to the caller.  The cache is replaced only after the
        atomic write succeeds, so failed writes do not expose unpersisted state.
        """
        with self.lock:
            data = deepcopy(self._live_data())
            result = fn(data)
            self.save(data)
            return result

    def _backup_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        corrupt_path = self.path.with_suffix(f"{self.path.suffix}.corrupt")
        try:
            os.replace(self.path, corrupt_path)
        except OSError:
            logger.exception("Failed to back up corrupt data file %s", self.path)
