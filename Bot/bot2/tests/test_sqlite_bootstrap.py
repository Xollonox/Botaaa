"""Regression tests for JSON-to-SQLite bootstrap behavior."""

from __future__ import annotations

import asyncio
from typing import Any

from bot.data.sqlite_store import SQLiteBattleRepository, SQLiteMarketRepository, SQLiteTradeRepository
from bot.services.battle_service import BattleService
from bot.services.market_service import MarketService
from bot.services.trade_service import TradeService


class FakeStorage:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def load(self) -> dict[str, Any]:
        return self.data

    def with_lock(self, fn):
        return fn(self.data)


def test_market_bootstrap_does_not_overwrite_existing_sqlite_state(tmp_path) -> None:
    repo = SQLiteMarketRepository(str(tmp_path / "market.sqlite3"))
    service = MarketService(
        repo,
        FakeStorage(
            {
                "cards": {},
                "market": {
                    "settings": {"enabled": True, "fee_percent": 5, "max_listings_per_user": 10},
                    "store": {"items": {"Card A": {"price": 10, "stock": 1, "enabled": True}}},
                    "listings": {"listing-a": {"sold": False, "listed_at": 1, "card_name": "Card A"}},
                },
            }
        ),
    )
    asyncio.run(service.bootstrap_from_json())

    stale_storage = FakeStorage(
        {
            "cards": {},
            "market": {
                "settings": {"enabled": True, "fee_percent": 99, "max_listings_per_user": 1},
                "store": {"items": {"Card A": {"price": 999, "stock": 999, "enabled": False}}},
                "listings": {},
            },
        }
    )
    asyncio.run(MarketService(repo, stale_storage).bootstrap_from_json())

    assert asyncio.run(repo.list_store_items())["Card A"] == {"price": 10, "stock": 1, "enabled": True}
    assert "listing-a" in asyncio.run(repo.list_active_listings())
    assert asyncio.run(repo.get_settings())["fee_percent"] == 5
    assert asyncio.run(repo.json_bootstrap_completed())


def test_trade_bootstrap_does_not_clear_existing_sqlite_state(tmp_path) -> None:
    repo = SQLiteTradeRepository(str(tmp_path / "trades.sqlite3"))
    asyncio.run(TradeService(repo, FakeStorage({"trades": {"pending": {"1": True}, "history": []}})).bootstrap_from_json())

    asyncio.run(TradeService(repo, FakeStorage({"trades": {"pending": {}, "history": []}})).bootstrap_from_json())

    assert asyncio.run(repo.is_pending("1"))
    assert asyncio.run(repo.json_bootstrap_completed())


def test_trade_offer_claim_is_atomic_and_releasable(tmp_path) -> None:
    repo = SQLiteTradeRepository(str(tmp_path / "trade-claims.sqlite3"))
    asyncio.run(repo.post_offer("offer", "1", "Poster", "A", "B", "uid-a", 10, 200))

    claimed = asyncio.run(repo.claim_offer("offer", 100))
    assert claimed is not None
    assert claimed["item_uid"] == "uid-a"
    assert asyncio.run(repo.claim_offer("offer", 100)) is None

    assert asyncio.run(repo.finish_offer("offer", "open"))
    assert asyncio.run(repo.claim_offer("offer", 100)) is not None
    assert asyncio.run(repo.finish_offer("offer", "accepted"))
    assert asyncio.run(repo.claim_offer("offer", 100)) is None


def test_expired_trade_offer_cannot_be_claimed_and_unlocks_exact_card(tmp_path, monkeypatch) -> None:
    repo = SQLiteTradeRepository(str(tmp_path / "trade-expiry.sqlite3"))
    data = {
        "players": {
            "1": {
                "user": {
                    "inventory": [
                        {"uid": "uid-a", "trade_locked": True},
                        {"uid": "uid-b", "trade_locked": True},
                    ]
                }
            }
        }
    }
    service = TradeService(repo, FakeStorage(data))
    asyncio.run(repo.post_offer("expired", "1", "Poster", "A", "B", "uid-a", 10, 50))
    monkeypatch.setattr("bot.services.trade_service.now_ts", lambda: 100)

    assert asyncio.run(service.claim_offer("expired")) is None
    expired = asyncio.run(service.expire_offers())
    assert [row["id"] for row in expired] == ["expired"]
    assert data["players"]["1"]["user"]["inventory"] == [
        {"uid": "uid-a", "trade_locked": False},
        {"uid": "uid-b", "trade_locked": True},
    ]


def test_battle_bootstrap_does_not_clear_existing_sqlite_state(tmp_path) -> None:
    repo = SQLiteBattleRepository(str(tmp_path / "battle.sqlite3"))
    asyncio.run(BattleService(
        repo,
        FakeStorage(
            {
                "battle": {
                    "queue": [{"user_id": "1", "joined_at": 1, "expires_at": 4_102_444_800}],
                    "pending_friendly": {},
                    "active": {},
                    "active_by_user": {},
                }
            }
        ),
    ).bootstrap_from_json())

    asyncio.run(BattleService(
        repo,
        FakeStorage({"battle": {"queue": [], "pending_friendly": {}, "active": {}, "active_by_user": {}}}),
    ).bootstrap_from_json())

    assert asyncio.run(repo.list_queue(0)) == [{"user_id": "1", "joined_at": 1, "expires_at": 4_102_444_800}]
    assert asyncio.run(repo.json_bootstrap_completed())
