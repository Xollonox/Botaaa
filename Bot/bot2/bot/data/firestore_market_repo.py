"""Firestore-backed replacement for :class:`bot.data.sqlite_store.SQLiteMarketRepository`.

Preserves the exact async method signatures used by ``MarketService`` so no
call site changes. Backing collections: ``market_settings`` (single doc
``main``), ``market_store_items`` (one doc per card), ``market_listings``
(one doc per listing). Filtering/sorting for listings is done client-side
to avoid requiring manually-created Firestore composite indexes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.base_query import FieldFilter

from .firestore_storage import _sanitize_for_firestore

_MIGRATIONS_COLLECTION = "app_migrations"
_SETTINGS_COLLECTION = "market_settings"
_SETTINGS_DOC_ID = "main"
_STORE_ITEMS_COLLECTION = "market_store_items"
_LISTINGS_COLLECTION = "market_listings"

_DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "fee_percent": 5,
    "max_listings_per_user": 10,
    "quick_sell_values": {},
    "price_band": {},
}


class FirestoreMarketRepository:
    JSON_BOOTSTRAP_KEY = "market_json_bootstrap_v1"

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
        """Return True once Firestore has state that should not be overwritten from JSON."""
        store_any = next(self._db.collection(_STORE_ITEMS_COLLECTION).limit(1).stream(), None)
        listing_any = next(self._db.collection(_LISTINGS_COLLECTION).limit(1).stream(), None)
        if store_any is not None or listing_any is not None:
            return True

        settings_doc = self._db.collection(_SETTINGS_COLLECTION).document(_SETTINGS_DOC_ID).get()
        if not settings_doc.exists:
            return False
        settings = settings_doc.to_dict() or {}
        return (
            not bool(settings.get("enabled", True))
            or int(settings.get("fee_percent", 5)) != 5
            or int(settings.get("max_listings_per_user", 10)) != 10
            or dict(settings.get("quick_sell_values") or {}) != {}
            or dict(settings.get("price_band") or {}) != {}
        )

    def _sync_seed_from_json_market(self, market: dict[str, Any]) -> None:
        settings = market.get("settings", {}) if isinstance(market, dict) else {}
        if not isinstance(settings, dict):
            settings = {}
        store = market.get("store", {}) if isinstance(market, dict) else {}
        if not isinstance(store, dict):
            store = {}
        items = store.get("items", {})
        if not isinstance(items, dict):
            items = {}

        settings_payload = {
            "enabled": bool(settings.get("enabled", True)),
            "fee_percent": int(settings.get("fee_percent", 5)),
            "max_listings_per_user": int(settings.get("max_listings_per_user", 10)),
            "quick_sell_values": _sanitize_for_firestore(dict(settings.get("quick_sell_values") or {})),
            "price_band": _sanitize_for_firestore(dict(settings.get("price_band") or {})),
        }
        self._db.collection(_SETTINGS_COLLECTION).document(_SETTINGS_DOC_ID).set(settings_payload)

        coll = self._db.collection(_STORE_ITEMS_COLLECTION)
        for doc in coll.stream():
            doc.reference.delete()
        for card_name, row in items.items():
            if not isinstance(row, dict):
                continue
            coll.document(str(card_name)).set(
                {
                    "price": int(row.get("price", 0)),
                    "stock": int(row.get("stock", 0)),
                    "enabled": bool(row.get("enabled", True)),
                }
            )

    def _sync_get_settings(self) -> dict[str, Any]:
        doc = self._db.collection(_SETTINGS_COLLECTION).document(_SETTINGS_DOC_ID).get()
        if not doc.exists:
            return dict(_DEFAULT_SETTINGS)
        data = doc.to_dict() or {}
        return {
            "enabled": bool(data.get("enabled", True)),
            "fee_percent": int(data.get("fee_percent", 5)),
            "max_listings_per_user": int(data.get("max_listings_per_user", 10)),
            "quick_sell_values": dict(data.get("quick_sell_values") or {}),
            "price_band": dict(data.get("price_band") or {}),
        }

    def _sync_update_setting(self, key: str, value: Any) -> None:
        if key not in {"enabled", "fee_percent", "max_listings_per_user"}:
            raise ValueError(f"Unsupported setting key: {key}")
        val: Any = bool(value) if key == "enabled" else int(value)
        self._db.collection(_SETTINGS_COLLECTION).document(_SETTINGS_DOC_ID).set({key: val}, merge=True)

    def _sync_replace_json_settings(self, quick_sell_values: dict[str, Any], price_band: dict[str, Any]) -> None:
        self._db.collection(_SETTINGS_COLLECTION).document(_SETTINGS_DOC_ID).set(
            {
                "quick_sell_values": _sanitize_for_firestore(dict(quick_sell_values)),
                "price_band": _sanitize_for_firestore(dict(price_band)),
            },
            merge=True,
        )

    def _sync_set_store_item(self, card_name: str, price: int, stock: int, enabled: bool = True) -> None:
        self._db.collection(_STORE_ITEMS_COLLECTION).document(str(card_name)).set(
            {"price": int(price), "stock": int(stock), "enabled": bool(enabled)}
        )

    def _sync_remove_store_item(self, card_name: str) -> None:
        self._db.collection(_STORE_ITEMS_COLLECTION).document(str(card_name)).delete()

    def _sync_toggle_store_item(self, card_name: str, enabled: bool) -> bool:
        ref = self._db.collection(_STORE_ITEMS_COLLECTION).document(str(card_name))
        if not ref.get().exists:
            return False
        ref.set({"enabled": bool(enabled)}, merge=True)
        return True

    def _sync_list_store_items(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for doc in self._db.collection(_STORE_ITEMS_COLLECTION).stream():
            data = doc.to_dict() or {}
            out[doc.id] = {
                "price": int(data.get("price", 0)),
                "stock": int(data.get("stock", 0)),
                "enabled": bool(data.get("enabled", True)),
            }
        return dict(sorted(out.items()))

    def _sync_seed_listings_from_json(self, listings: dict[str, Any]) -> None:
        if not isinstance(listings, dict):
            return
        coll = self._db.collection(_LISTINGS_COLLECTION)
        for doc in coll.stream():
            doc.reference.delete()
        for lid, row in listings.items():
            if not isinstance(row, dict):
                continue
            coll.document(str(lid)).set(_sanitize_for_firestore(dict(row)))

    def _sync_upsert_listing(self, listing_id: str, payload: dict[str, Any]) -> None:
        self._db.collection(_LISTINGS_COLLECTION).document(str(listing_id)).set(_sanitize_for_firestore(dict(payload)))

    def _sync_delete_listing(self, listing_id: str) -> bool:
        ref = self._db.collection(_LISTINGS_COLLECTION).document(str(listing_id))
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def _sync_get_listing(self, listing_id: str) -> dict[str, Any] | None:
        doc = self._db.collection(_LISTINGS_COLLECTION).document(str(listing_id)).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data if isinstance(data, dict) else None

    def _sync_list_active_listings(self, limit: int = 200) -> dict[str, dict[str, Any]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        query = self._db.collection(_LISTINGS_COLLECTION).where(filter=FieldFilter("sold", "==", False))
        for doc in query.stream():
            rows.append((doc.id, doc.to_dict() or {}))
        rows.sort(key=lambda pair: int(pair[1].get("listed_at", 0)), reverse=True)
        return {lid: data for lid, data in rows[:limit]}

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

    async def seed_from_json_market(self, market: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_seed_from_json_market, market)

    async def get_settings(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_get_settings)

    async def update_setting(self, key: str, value: Any) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_update_setting, key, value)

    async def replace_json_settings(self, quick_sell_values: dict[str, Any], price_band: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_replace_json_settings, quick_sell_values, price_band)

    async def set_store_item(self, card_name: str, price: int, stock: int, enabled: bool = True) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_set_store_item, card_name, price, stock, enabled)

    async def remove_store_item(self, card_name: str) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_remove_store_item, card_name)

    async def toggle_store_item(self, card_name: str, enabled: bool) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_toggle_store_item, card_name, enabled)

    async def list_store_items(self) -> dict[str, dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_store_items)

    async def seed_listings_from_json(self, listings: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_seed_listings_from_json, listings)

    async def upsert_listing(self, listing_id: str, payload: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_upsert_listing, listing_id, payload)

    async def delete_listing(self, listing_id: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_delete_listing, listing_id)

    async def get_listing(self, listing_id: str) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_get_listing, listing_id)

    async def list_active_listings(self, limit: int = 200) -> dict[str, dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_active_listings, limit)
