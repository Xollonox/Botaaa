"""Thread-safe JSON storage with atomic writes."""

from __future__ import annotations

import json
import logging
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

    def save(self, data: dict[str, Any]) -> None:
        """Write *data* to disk and refresh the in‑memory cache.

        ``data`` is expected to be the same instance returned by ``load`` (or a
        copy that the caller wants to persist).  The method sanitises the payload,
        writes it atomically, and then stores the reference in ``self._cache``.

        The cache is updated before the atomic write. The write stays
        synchronous so two consecutive saves cannot reach disk out of order.
        """
        self._cache = data  # cache updated instantly — no I/O

        def _write() -> None:
            sanitized = _sanitize_for_json(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(sanitized, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)

        _write()

    def with_lock(self, fn: Callable[[dict[str, Any]], T]) -> T:
        """Execute *fn* with exclusive access to the storage.

        ``fn`` receives the live data dict, may modify it, and its return value is
        propagated back to the caller.  The lock guarantees that only one task
        writes to the file at a time, while the cache stays consistent.
        """
        with self.lock:
            data = self._live_data()
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
