"""One-time migration of Bot/bot2 data from the JSON blob + SQLite DB to Firestore.

Run once, manually, after FIREBASE_PROJECT_ID / FIREBASE_CREDENTIALS_PATH are
configured in Bot/bot2/.env:

    cd Bot/bot2 && python3 scripts/migrate_to_firestore.py

Local ``lookism_data.json`` / ``lookism_data.sqlite3`` are left on disk
untouched afterward — they are the rollback path if anything looks wrong
post-migration. The running bot stops reading them once main.py's Firestore
wiring is deployed; this script only pushes their contents to Firestore.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import DATA_PATH, FIREBASE_CREDENTIALS_PATH, FIREBASE_PROJECT_ID, SQLITE_PATH
from bot.data.defaults import build_default_data, ensure_structure
from bot.data.firestore_client import get_firestore_client
from bot.data.firestore_storage import FirestoreStorage


def _load_json_blob() -> dict:
    if not os.path.isfile(DATA_PATH):
        print(f"No JSON data file found at {DATA_PATH}; using defaults.")
        return build_default_data()
    with open(DATA_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return ensure_structure(data)


def _connect_sqlite() -> sqlite3.Connection | None:
    if not os.path.isfile(SQLITE_PATH):
        print(f"No SQLite database found at {SQLITE_PATH}; skipping market/trade/battle table migration.")
        return None
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_json_blob(client) -> None:
    print("Migrating JSON blob (players + global fields) into Firestore...")
    data = _load_json_blob()
    FirestoreStorage(client)._write_full(data)
    print(f"  Wrote bot_state/global and {len(data.get('players', {}))} player document(s).")


def migrate_app_migrations(client, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT key, completed_at FROM app_migrations").fetchall()
    coll = client.collection("app_migrations")
    for row in rows:
        coll.document(str(row["key"])).set({"completed_at": int(row["completed_at"])})
    print(f"  Migrated {len(rows)} bootstrap-completion marker(s).")


def migrate_market(client, conn: sqlite3.Connection) -> None:
    print("Migrating market tables...")

    settings_row = conn.execute("SELECT * FROM market_settings WHERE id = 1").fetchone()
    if settings_row is not None:
        client.collection("market_settings").document("main").set(
            {
                "enabled": bool(settings_row["enabled"]),
                "fee_percent": int(settings_row["fee_percent"]),
                "max_listings_per_user": int(settings_row["max_listings_per_user"]),
                "quick_sell_values": json.loads(settings_row["quick_sell_values_json"] or "{}"),
                "price_band": json.loads(settings_row["price_band_json"] or "{}"),
            }
        )

    items = conn.execute("SELECT card_name, price, stock, enabled FROM market_store_items").fetchall()
    for item in items:
        client.collection("market_store_items").document(str(item["card_name"])).set(
            {"price": int(item["price"]), "stock": int(item["stock"]), "enabled": bool(item["enabled"])}
        )

    listings = conn.execute("SELECT id, payload_json FROM market_listings").fetchall()
    migrated_listings = 0
    for listing in listings:
        try:
            payload = json.loads(listing["payload_json"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            client.collection("market_listings").document(str(listing["id"])).set(payload)
            migrated_listings += 1

    print(f"  Migrated settings, {len(items)} store item(s), {migrated_listings} listing(s).")


def migrate_trade(client, conn: sqlite3.Connection) -> None:
    print("Migrating trade tables...")

    pending = conn.execute("SELECT user_id FROM trade_pending").fetchall()
    for row in pending:
        client.collection("trade_pending").document(str(row["user_id"])).set({})

    history = conn.execute("SELECT a_id, b_id, resolved_at, payload_json FROM trade_history").fetchall()
    migrated_history = 0
    for row in history:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        payload["a_id"] = str(row["a_id"])
        payload["b_id"] = str(row["b_id"])
        payload["resolved_at"] = int(row["resolved_at"])
        client.collection("trade_history").add(payload)
        migrated_history += 1

    offers = conn.execute(
        "SELECT id, poster_id, poster_name, have_card, want_card, item_uid, created_at, expires_at, status "
        "FROM trade_offer_board"
    ).fetchall()
    for row in offers:
        # A process may have died mid-claim; treat 'processing' as 'open' again,
        # mirroring the repo's own boot-time recovery behavior.
        status = "open" if row["status"] == "processing" else row["status"]
        client.collection("trade_offer_board").document(str(row["id"])).set(
            {
                "poster_id": row["poster_id"],
                "poster_name": row["poster_name"],
                "have_card": row["have_card"],
                "want_card": row["want_card"],
                "item_uid": row["item_uid"],
                "created_at": int(row["created_at"]),
                "expires_at": int(row["expires_at"]),
                "status": status,
            }
        )

    print(f"  Migrated {len(pending)} pending lock(s), {migrated_history} history row(s), {len(offers)} offer(s).")


def migrate_battle(client, conn: sqlite3.Connection) -> None:
    print("Migrating battle tables...")

    queue = conn.execute("SELECT user_id, joined_at, expires_at FROM battle_queue").fetchall()
    for row in queue:
        client.collection("battle_queue").document(str(row["user_id"])).set(
            {"joined_at": int(row["joined_at"]), "expires_at": int(row["expires_at"])}
        )

    pending = conn.execute("SELECT target_id, payload_json FROM battle_pending_friendly").fetchall()
    migrated_pending = 0
    for row in pending:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            client.collection("battle_pending_friendly").document(str(row["target_id"])).set(payload)
            migrated_pending += 1

    active = conn.execute("SELECT user_id, battle_id FROM battle_active_by_user").fetchall()
    for row in active:
        client.collection("battle_active_by_user").document(str(row["user_id"])).set(
            {"battle_id": str(row["battle_id"])}
        )

    print(f"  Migrated {len(queue)} queue entry(ies), {migrated_pending} pending friendly, {len(active)} active battle(s).")


def main() -> None:
    if not FIREBASE_PROJECT_ID or not FIREBASE_CREDENTIALS_PATH:
        raise SystemExit(
            "FIREBASE_PROJECT_ID and FIREBASE_CREDENTIALS_PATH must be set in Bot/bot2/.env before migrating."
        )
    if not os.path.isfile(FIREBASE_CREDENTIALS_PATH):
        raise SystemExit(f"FIREBASE_CREDENTIALS_PATH does not point to a file: {FIREBASE_CREDENTIALS_PATH}")

    client = get_firestore_client(FIREBASE_PROJECT_ID, FIREBASE_CREDENTIALS_PATH)

    migrate_json_blob(client)

    conn = _connect_sqlite()
    if conn is not None:
        try:
            migrate_app_migrations(client, conn)
            migrate_market(client, conn)
            migrate_trade(client, conn)
            migrate_battle(client, conn)
        finally:
            conn.close()

    print("Migration complete. Local lookism_data.json / lookism_data.sqlite3 are left untouched as a backup.")


if __name__ == "__main__":
    main()
