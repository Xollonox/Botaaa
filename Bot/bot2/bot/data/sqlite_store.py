"""SQLite repositories for incremental migration from JSON storage."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_migrations (
            key TEXT PRIMARY KEY,
            completed_at INTEGER NOT NULL
        )
        """
    )


def _migration_done(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT 1 FROM app_migrations WHERE key = ?", (key,)).fetchone()
    return row is not None


def _mark_migration_done(conn: sqlite3.Connection, key: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO app_migrations (key, completed_at) VALUES (?, ?)",
        (key, int(time.time())),
    )


class SQLiteMarketRepository:
    JSON_BOOTSTRAP_KEY = "market_json_bootstrap_v1"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _ensure_migration_table(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    fee_percent INTEGER NOT NULL DEFAULT 5,
                    max_listings_per_user INTEGER NOT NULL DEFAULT 10,
                    quick_sell_values_json TEXT NOT NULL DEFAULT '{}',
                    price_band_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_store_items (
                    card_name TEXT PRIMARY KEY,
                    price INTEGER NOT NULL DEFAULT 0,
                    stock INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_listings (
                    id TEXT PRIMARY KEY,
                    sold INTEGER NOT NULL DEFAULT 0,
                    listed_at INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO market_settings
                (id, enabled, fee_percent, max_listings_per_user, quick_sell_values_json, price_band_json)
                VALUES (1, 1, 5, 10, '{}', '{}')
                """
            )
            conn.commit()

    def json_bootstrap_completed(self) -> bool:
        with self._connect() as conn:
            return _migration_done(conn, self.JSON_BOOTSTRAP_KEY)

    def mark_json_bootstrap_completed(self) -> None:
        with self._connect() as conn:
            _mark_migration_done(conn, self.JSON_BOOTSTRAP_KEY)
            conn.commit()

    def has_persisted_state(self) -> bool:
        """Return True once SQLite has state that should not be overwritten from JSON."""
        with self._connect() as conn:
            settings = conn.execute(
                """
                SELECT enabled, fee_percent, max_listings_per_user, quick_sell_values_json, price_band_json
                FROM market_settings
                WHERE id = 1
                """
            ).fetchone()
            store_count = conn.execute("SELECT COUNT(*) FROM market_store_items").fetchone()[0]
            listing_count = conn.execute("SELECT COUNT(*) FROM market_listings").fetchone()[0]

        if int(store_count) > 0 or int(listing_count) > 0:
            return True
        if settings is None:
            return False
        return (
            int(settings["enabled"]) != 1
            or int(settings["fee_percent"]) != 5
            or int(settings["max_listings_per_user"]) != 10
            or str(settings["quick_sell_values_json"] or "{}") != "{}"
            or str(settings["price_band_json"] or "{}") != "{}"
        )

    def seed_from_json_market(self, market: dict[str, Any]) -> None:
        settings = market.get("settings", {}) if isinstance(market, dict) else {}
        if not isinstance(settings, dict):
            settings = {}
        store = market.get("store", {}) if isinstance(market, dict) else {}
        if not isinstance(store, dict):
            store = {}
        items = store.get("items", {})
        if not isinstance(items, dict):
            items = {}

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE market_settings
                SET enabled = ?, fee_percent = ?, max_listings_per_user = ?,
                    quick_sell_values_json = ?, price_band_json = ?
                WHERE id = 1
                """,
                (
                    1 if bool(settings.get("enabled", True)) else 0,
                    int(settings.get("fee_percent", 5)),
                    int(settings.get("max_listings_per_user", 10)),
                    json.dumps(settings.get("quick_sell_values", {})),
                    json.dumps(settings.get("price_band", {})),
                ),
            )
            conn.execute("DELETE FROM market_store_items")
            for card_name, row in items.items():
                if not isinstance(row, dict):
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_store_items (card_name, price, stock, enabled)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(card_name),
                        int(row.get("price", 0)),
                        int(row.get("stock", 0)),
                        1 if bool(row.get("enabled", True)) else 0,
                    ),
                )
            conn.commit()

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM market_settings WHERE id = 1").fetchone()
        if row is None:
            return {
                "enabled": True,
                "fee_percent": 5,
                "max_listings_per_user": 10,
                "quick_sell_values": {},
                "price_band": {},
            }
        return {
            "enabled": bool(row["enabled"]),
            "fee_percent": int(row["fee_percent"]),
            "max_listings_per_user": int(row["max_listings_per_user"]),
            "quick_sell_values": json.loads(row["quick_sell_values_json"] or "{}"),
            "price_band": json.loads(row["price_band_json"] or "{}"),
        }

    def update_setting(self, key: str, value: Any) -> None:
        column_map = {
            "enabled": "enabled",
            "fee_percent": "fee_percent",
            "max_listings_per_user": "max_listings_per_user",
        }
        col = column_map.get(key)
        if not col:
            raise ValueError(f"Unsupported setting key: {key}")
        val = int(value) if col != "enabled" else (1 if bool(value) else 0)
        with self._connect() as conn:
            conn.execute(f"UPDATE market_settings SET {col} = ? WHERE id = 1", (val,))
            conn.commit()

    def replace_json_settings(self, quick_sell_values: dict[str, Any], price_band: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE market_settings
                SET quick_sell_values_json = ?, price_band_json = ?
                WHERE id = 1
                """,
                (json.dumps(quick_sell_values), json.dumps(price_band)),
            )
            conn.commit()

    def set_store_item(self, card_name: str, price: int, stock: int, enabled: bool = True) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_store_items (card_name, price, stock, enabled)
                VALUES (?, ?, ?, ?)
                """,
                (card_name, int(price), int(stock), 1 if enabled else 0),
            )
            conn.commit()

    def remove_store_item(self, card_name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM market_store_items WHERE card_name = ?", (card_name,))
            conn.commit()

    def toggle_store_item(self, card_name: str, enabled: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE market_store_items SET enabled = ? WHERE card_name = ?",
                (1 if enabled else 0, card_name),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_store_items(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT card_name, price, stock, enabled FROM market_store_items ORDER BY card_name ASC"
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            out[str(row["card_name"])] = {
                "price": int(row["price"]),
                "stock": int(row["stock"]),
                "enabled": bool(row["enabled"]),
            }
        return out

    def seed_listings_from_json(self, listings: dict[str, Any]) -> None:
        if not isinstance(listings, dict):
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM market_listings")
            for lid, row in listings.items():
                if not isinstance(row, dict):
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_listings (id, sold, listed_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(lid),
                        1 if bool(row.get("sold", False)) else 0,
                        int(row.get("listed_at", 0)),
                        json.dumps(row),
                    ),
                )
            conn.commit()

    def upsert_listing(self, listing_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_listings (id, sold, listed_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(listing_id),
                    1 if bool(payload.get("sold", False)) else 0,
                    int(payload.get("listed_at", 0)),
                    json.dumps(payload),
                ),
            )
            conn.commit()

    def delete_listing(self, listing_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM market_listings WHERE id = ?", (str(listing_id),))
            conn.commit()
            return cur.rowcount > 0

    def get_listing(self, listing_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM market_listings WHERE id = ?",
                (str(listing_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def list_active_listings(self, limit: int = 200) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, payload_json FROM market_listings WHERE sold = 0 ORDER BY listed_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if isinstance(payload, dict):
                out[str(row["id"])] = payload
        return out


class SQLiteTradeRepository:
    JSON_BOOTSTRAP_KEY = "trade_json_bootstrap_v1"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _ensure_migration_table(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_pending (
                    user_id TEXT PRIMARY KEY
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    a_id TEXT NOT NULL,
                    b_id TEXT NOT NULL,
                    resolved_at INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_offer_board (
                    id TEXT PRIMARY KEY,
                    poster_id TEXT NOT NULL,
                    poster_name TEXT NOT NULL,
                    have_card TEXT NOT NULL,
                    want_card TEXT NOT NULL,
                    item_uid TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open'
                )
                """
            )
            conn.commit()

    def json_bootstrap_completed(self) -> bool:
        with self._connect() as conn:
            return _migration_done(conn, self.JSON_BOOTSTRAP_KEY)

    def mark_json_bootstrap_completed(self) -> None:
        with self._connect() as conn:
            _mark_migration_done(conn, self.JSON_BOOTSTRAP_KEY)
            conn.commit()

    def has_persisted_state(self) -> bool:
        """Return True once trade rows exist in SQLite."""
        with self._connect() as conn:
            pending_count = conn.execute("SELECT COUNT(*) FROM trade_pending").fetchone()[0]
            history_count = conn.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0]
        return int(pending_count) > 0 or int(history_count) > 0

    def seed_from_json_trades(self, trades: dict[str, Any]) -> None:
        pending = trades.get("pending", {}) if isinstance(trades, dict) else {}
        history = trades.get("history", []) if isinstance(trades, dict) else []
        if not isinstance(pending, dict):
            pending = {}
        if not isinstance(history, list):
            history = []

        with self._connect() as conn:
            conn.execute("DELETE FROM trade_pending")
            for uid, active in pending.items():
                if not active:
                    continue
                conn.execute("INSERT OR REPLACE INTO trade_pending (user_id) VALUES (?)", (str(uid),))

            conn.execute("DELETE FROM trade_history")
            for row in history:
                if not isinstance(row, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO trade_history (a_id, b_id, resolved_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(row.get("a_id", "")),
                        str(row.get("b_id", "")),
                        int(row.get("resolved_at", row.get("created_at", 0))),
                        json.dumps(row),
                    ),
                )
            conn.commit()

    def is_pending(self, user_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM trade_pending WHERE user_id = ?", (str(user_id),)).fetchone()
        return row is not None

    def add_pending_pair(self, a_id: str, b_id: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO trade_pending (user_id) VALUES (?)", (str(a_id),))
            conn.execute("INSERT OR REPLACE INTO trade_pending (user_id) VALUES (?)", (str(b_id),))
            conn.commit()

    def remove_pending(self, user_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM trade_pending WHERE user_id = ?", (str(user_id),))
            conn.commit()
            return cur.rowcount > 0

    def remove_pending_pair(self, a_id: str, b_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM trade_pending WHERE user_id = ?", (str(a_id),))
            conn.execute("DELETE FROM trade_pending WHERE user_id = ?", (str(b_id),))
            conn.commit()

    def list_pending(self) -> dict[str, bool]:
        with self._connect() as conn:
            rows = conn.execute("SELECT user_id FROM trade_pending").fetchall()
        return {str(r["user_id"]): True for r in rows}

    def append_history(self, row: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_history (a_id, b_id, resolved_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(row.get("a_id", "")),
                    str(row.get("b_id", "")),
                    int(row.get("resolved_at", row.get("created_at", 0))),
                    json.dumps(row),
                ),
            )
            # Keep history bounded
            conn.execute(
                """
                DELETE FROM trade_history
                WHERE id NOT IN (
                    SELECT id FROM trade_history ORDER BY id DESC LIMIT 200
                )
                """
            )
            conn.commit()

    def recent_history_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM trade_history
                WHERE a_id = ? OR b_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(user_id), str(user_id), int(limit)),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if isinstance(payload, dict):
                out.append(payload)
        return out

    def post_offer(self, offer_id: str, poster_id: str, poster_name: str, have_card: str, want_card: str, item_uid: str, created_at: int, expires_at: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_offer_board (id, poster_id, poster_name, have_card, want_card, item_uid, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (offer_id, poster_id, poster_name, have_card, want_card, item_uid, created_at, expires_at),
            )
            conn.commit()

    def get_open_offers(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            now = int(time.time())
            rows = conn.execute(
                """
                SELECT id, poster_id, poster_name, have_card, want_card, created_at, expires_at, status
                FROM trade_offer_board
                WHERE status = 'open' AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def cancel_offer(self, offer_id: str, poster_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE trade_offer_board SET status = 'cancelled' WHERE id = ? AND poster_id = ?",
                (offer_id, poster_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def accept_offer(self, offer_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trade_offer_board WHERE id = ? AND status = 'open'",
                (offer_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE trade_offer_board SET status = 'accepted' WHERE id = ?", (offer_id,))
            conn.commit()
        return dict(row) if row else None


class SQLiteBattleRepository:
    JSON_BOOTSTRAP_KEY = "battle_json_bootstrap_v1"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _ensure_migration_table(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS battle_queue (
                    user_id TEXT PRIMARY KEY,
                    joined_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS battle_pending_friendly (
                    target_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS battle_active_by_user (
                    user_id TEXT PRIMARY KEY,
                    battle_id TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def json_bootstrap_completed(self) -> bool:
        with self._connect() as conn:
            return _migration_done(conn, self.JSON_BOOTSTRAP_KEY)

    def mark_json_bootstrap_completed(self) -> None:
        with self._connect() as conn:
            _mark_migration_done(conn, self.JSON_BOOTSTRAP_KEY)
            conn.commit()

    def has_persisted_state(self) -> bool:
        """Return True once battle rows exist in SQLite."""
        with self._connect() as conn:
            queue_count = conn.execute("SELECT COUNT(*) FROM battle_queue").fetchone()[0]
            pending_count = conn.execute("SELECT COUNT(*) FROM battle_pending_friendly").fetchone()[0]
            active_count = conn.execute("SELECT COUNT(*) FROM battle_active_by_user").fetchone()[0]
        return int(queue_count) > 0 or int(pending_count) > 0 or int(active_count) > 0

    def seed_from_json_battle(self, battle: dict[str, Any]) -> None:
        queue = battle.get("queue", []) if isinstance(battle, dict) else []
        pending = battle.get("pending_friendly", {}) if isinstance(battle, dict) else {}
        active_by_user = battle.get("active_by_user", {}) if isinstance(battle, dict) else {}
        if not isinstance(queue, list):
            queue = []
        if not isinstance(pending, dict):
            pending = {}
        if not isinstance(active_by_user, dict):
            active_by_user = {}

        with self._connect() as conn:
            conn.execute("DELETE FROM battle_queue")
            for q in queue:
                if not isinstance(q, dict):
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO battle_queue (user_id, joined_at, expires_at) VALUES (?, ?, ?)",
                    (str(q.get("user_id", "")), int(q.get("joined_at", 0)), int(q.get("expires_at", 0))),
                )

            conn.execute("DELETE FROM battle_pending_friendly")
            for target_id, payload in pending.items():
                if not isinstance(payload, dict):
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO battle_pending_friendly (target_id, payload_json, expires_at) VALUES (?, ?, ?)",
                    (str(target_id), json.dumps(payload), int(payload.get("expires_at", 0))),
                )

            conn.execute("DELETE FROM battle_active_by_user")
            for uid, bid in active_by_user.items():
                conn.execute(
                    "INSERT OR REPLACE INTO battle_active_by_user (user_id, battle_id) VALUES (?, ?)",
                    (str(uid), str(bid)),
                )
            conn.commit()

    def list_queue(self, now_ts: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.execute("DELETE FROM battle_queue WHERE expires_at <= ?", (int(now_ts),))
            rows = conn.execute(
                "SELECT user_id, joined_at, expires_at FROM battle_queue ORDER BY joined_at ASC"
            ).fetchall()
            conn.commit()
        return [
            {"user_id": str(r["user_id"]), "joined_at": int(r["joined_at"]), "expires_at": int(r["expires_at"])}
            for r in rows
        ]

    def upsert_queue_entry(self, user_id: str, joined_at: int, expires_at: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO battle_queue (user_id, joined_at, expires_at) VALUES (?, ?, ?)",
                (str(user_id), int(joined_at), int(expires_at)),
            )
            conn.commit()

    def remove_queue_user(self, user_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM battle_queue WHERE user_id = ?", (str(user_id),))
            conn.commit()
            return cur.rowcount > 0

    def remove_queue_users(self, user_ids: list[str]) -> None:
        if not user_ids:
            return
        with self._connect() as conn:
            conn.executemany("DELETE FROM battle_queue WHERE user_id = ?", [(str(uid),) for uid in user_ids])
            conn.commit()

    def list_pending_friendly(self, now_ts: int) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            conn.execute("DELETE FROM battle_pending_friendly WHERE expires_at <= ?", (int(now_ts),))
            rows = conn.execute("SELECT target_id, payload_json FROM battle_pending_friendly").fetchall()
            conn.commit()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            try:
                payload = json.loads(r["payload_json"])
            except Exception:
                continue
            if isinstance(payload, dict):
                out[str(r["target_id"])] = payload
        return out

    def upsert_pending_friendly(self, target_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO battle_pending_friendly (target_id, payload_json, expires_at) VALUES (?, ?, ?)",
                (str(target_id), json.dumps(payload), int(payload.get("expires_at", 0))),
            )
            conn.commit()

    def remove_pending_friendly(self, target_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM battle_pending_friendly WHERE target_id = ?", (str(target_id),))
            conn.commit()
            return cur.rowcount > 0

    def list_active_by_user(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT user_id, battle_id FROM battle_active_by_user").fetchall()
        return {str(r["user_id"]): str(r["battle_id"]) for r in rows}

    def set_active_by_user(self, mapping: dict[str, str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM battle_active_by_user")
            for uid, bid in mapping.items():
                conn.execute(
                    "INSERT OR REPLACE INTO battle_active_by_user (user_id, battle_id) VALUES (?, ?)",
                    (str(uid), str(bid)),
                )
            conn.commit()
