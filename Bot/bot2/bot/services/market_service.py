"""Market service backed by SQLite with JSON mirror for compatibility."""

from __future__ import annotations

from typing import Any

from bot.data.sqlite_store import SQLiteMarketRepository
from bot.utils.market_logic import ensure_market_structure


class MarketService:
    def __init__(self, repo: SQLiteMarketRepository, storage: Any) -> None:
        self.repo = repo
        self.storage = storage

    def bootstrap_from_json(self) -> None:
        if self.repo.json_bootstrap_completed():
            return
        if self.repo.has_persisted_state():
            self.repo.mark_json_bootstrap_completed()
            return
        data = self.storage.load()
        ensure_market_structure(data)
        market = data.get("market", {})
        if not isinstance(market, dict):
            market = {}
        self.repo.seed_from_json_market(market)
        listings = market.get("listings", {})
        if isinstance(listings, dict):
            self.repo.seed_listings_from_json(listings)
        self.repo.mark_json_bootstrap_completed()

    def set_enabled(self, enabled: bool) -> None:
        self.repo.update_setting("enabled", bool(enabled))
        self.storage.with_lock(
            lambda d: ensure_market_structure(d)["market"]["settings"].__setitem__("enabled", bool(enabled))
        )

    def set_fee_percent(self, fee_percent: int) -> None:
        self.repo.update_setting("fee_percent", int(fee_percent))
        self.storage.with_lock(
            lambda d: ensure_market_structure(d)["market"]["settings"].__setitem__("fee_percent", int(fee_percent))
        )

    def set_max_listings(self, max_listings_per_user: int) -> None:
        self.repo.update_setting("max_listings_per_user", int(max_listings_per_user))
        self.storage.with_lock(
            lambda d: ensure_market_structure(d)["market"]["settings"].__setitem__(
                "max_listings_per_user", int(max_listings_per_user)
            )
        )

    def upsert_store_item(self, card_name: str, stock: int, price_override: int | None = None) -> tuple[bool, str]:
        def mutate(d: dict[str, Any]) -> tuple[bool, str, int]:
            ensure_market_structure(d)
            cards = d.get("cards", {})
            if not isinstance(cards, dict) or card_name not in cards:
                return False, "card_missing", 0
            items = d["market"]["store"]["items"]
            prev = items.get(card_name, {}) if isinstance(items, dict) else {}
            price = int(price_override) if price_override is not None else int(prev.get("price", 0))
            items[card_name] = {"price": price, "stock": int(stock), "enabled": True}
            return True, "ok", price

        ok, reason, price = self.storage.with_lock(mutate)
        if not ok:
            return ok, reason
        self.repo.set_store_item(card_name=card_name, price=price, stock=int(stock), enabled=True)
        return True, "ok"

    def remove_store_item(self, card_name: str) -> None:
        self.repo.remove_store_item(card_name)
        self.storage.with_lock(lambda d: ensure_market_structure(d)["market"]["store"]["items"].pop(card_name, None))

    def toggle_store_item(self, card_name: str, enabled: bool) -> tuple[bool, str]:
        ok = self.repo.toggle_store_item(card_name, enabled)
        if not ok:
            return False, "store_item_missing"

        def mutate(d: dict[str, Any]) -> tuple[bool, str]:
            ensure_market_structure(d)
            items = d["market"]["store"]["items"]
            row = items.get(card_name) if isinstance(items, dict) else None
            if not isinstance(row, dict):
                return False, "store_item_missing"
            row["enabled"] = bool(enabled)
            return True, "ok"

        return self.storage.with_lock(mutate)

    def get_settings(self) -> dict[str, Any]:
        return self.repo.get_settings()

    def get_active_listings(self) -> dict[str, dict[str, Any]]:
        return self.repo.list_active_listings()

    def get_listing(self, listing_id: str) -> dict[str, Any] | None:
        return self.repo.get_listing(listing_id)

    def upsert_listing(self, listing_id: str, payload: dict[str, Any]) -> None:
        self.repo.upsert_listing(listing_id, payload)

    def delete_listing(self, listing_id: str) -> bool:
        return self.repo.delete_listing(listing_id)

    def hydrate_json_market_listings(self, data: dict[str, Any]) -> dict[str, Any]:
        ensure_market_structure(data)
        active = self.get_active_listings()
        data["market"]["listings"] = active
        return data

    def set_quick_sell_value(self, rarity: str, value: int) -> None:
        settings = self.repo.get_settings()
        qsv = settings.get("quick_sell_values", {})
        if not isinstance(qsv, dict):
            qsv = {}
        qsv[str(rarity)] = int(value)
        self.repo.replace_json_settings(
            quick_sell_values=qsv,
            price_band=settings.get("price_band", {}),
        )

        def mutate(d: dict[str, Any]) -> None:
            ensure_market_structure(d)
            d["market"]["settings"].setdefault("quick_sell_values", {})[str(rarity)] = int(value)

        self.storage.with_lock(mutate)
