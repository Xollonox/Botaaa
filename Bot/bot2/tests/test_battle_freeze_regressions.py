from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.features.battle import BattleCog
from bot.features.battle_views import ForfeitButton, TurnView
from bot.utils import battle_state


def _fighter(uid: str, card_name: str) -> dict:
    return {
        "uid": uid,
        "card_name": card_name,
        "stars": 1,
        "assigned_attacks": {"normal": ["jab"]},
    }


def _battle_data() -> dict:
    card = {
        "rarity": "Common",
        "stats": {
            "strength": 20,
            "speed": 20,
            "endurance": 100,
            "technique": 20,
            "iq": 20,
            "battle_iq": 20,
        },
        "moves": {"normal": ["jab"]},
    }
    return {
        "cards": {"A": card, "B": card},
        "players": {
            "u1": {"user": {"inventory": [_fighter("a1", "A")]}},
            "u2": {"user": {"inventory": [_fighter("b1", "B")]}},
        },
        "battle": {"queue": [], "pending_friendly": {}, "active": {}, "active_by_user": {}},
    }


def test_apply_move_sets_real_turn_timestamp(monkeypatch) -> None:
    data = _battle_data()
    battle_id = battle_state.create_battle_state(data, "ranked", "u1", "u2", ["a1"], ["b1"], 1_000)

    monkeypatch.setattr(battle_state, "now_ts", lambda: 2_000)
    result = battle_state.apply_move(data, battle_id, "u1", "normal", "jab")

    assert result["ok"] is True
    assert data["battle"]["active"][battle_id]["turn_started_at"] == 2_000


def test_battle_reads_card_stats_by_display_name_when_catalog_key_differs() -> None:
    data = {
        "cards": {
            "Custom Storage Key": {
                "name": "New Custom Fighter",
                "rarity": "Legendary",
                "stats": {
                    "strength": 77,
                    "speed": 66,
                    "endurance": 55,
                    "technique": 44,
                    "iq": 33,
                    "battle_iq": 22,
                },
            },
            "Opponent": {
                "name": "Opponent",
                "rarity": "Common",
                "stats": {
                    "strength": 10,
                    "speed": 10,
                    "endurance": 10,
                    "technique": 10,
                    "iq": 10,
                    "battle_iq": 10,
                },
            },
        },
        "players": {
            "u1": {"user": {"inventory": [_fighter("a1", "New Custom Fighter")]}},
            "u2": {"user": {"inventory": [_fighter("b1", "Opponent")]}},
        },
        "battle": {"queue": [], "pending_friendly": {}, "active": {}, "active_by_user": {}},
    }

    battle_id = battle_state.create_battle_state(data, "ranked", "u1", "u2", ["a1"], ["b1"], 1_000)
    stats = data["battle"]["active"][battle_id]["players"]["u1"]["stats"]["a1"]

    assert stats["strength"] == 79
    assert stats["speed"] == 68
    assert stats["endurance"] == 57
    assert stats["technique"] == 46
    assert stats["iq"] == 35
    assert stats["biq"] == 24


def test_friendly_timeout_cpu_handler_exists() -> None:
    assert callable(getattr(BattleCog, "_friendly_timeout_to_cpu", None))


def test_turn_view_does_not_have_discord_timeout() -> None:
    view = TurnView(object(), "battle-1", "u1", [], [], [])  # type: ignore[arg-type]

    assert view.timeout is None


class FakeStorage:
    def __init__(self, data: dict) -> None:
        self.data = data

    def load(self) -> dict:
        return self.data

    def with_lock(self, fn):
        return fn(self.data)


class FakeBattleService:
    def __init__(self) -> None:
        self.removed_queue_users: list[str] = []
        self.removed_pending_targets: list[str] = []
        self.synced_payloads: list[dict] = []

    async def hydrate_json_state(self, data: dict) -> dict:
        return data

    async def remove_queue_user(self, user_id: str) -> bool:
        self.removed_queue_users.append(str(user_id))
        return False

    async def remove_pending_friendly(self, target_id: str) -> bool:
        self.removed_pending_targets.append(str(target_id))
        return False

    async def sync_active_by_user_from_data(self, data: dict) -> None:
        self.synced_payloads.append(data)


class FakeTask:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


def _make_cog(data: dict) -> tuple[BattleCog, FakeBattleService]:
    service = FakeBattleService()
    bot = SimpleNamespace(storage=FakeStorage(data), battle_service=service)
    return BattleCog(bot), service  # type: ignore[arg-type]


def test_remove_ranked_queue_state_clears_json_and_task_even_if_sqlite_is_stale() -> None:
    data = {
        "battle": {
            "queue": [{"user_id": "u1", "joined_at": 1, "expires_at": 999999}],
            "pending_friendly": {},
            "active": {},
            "active_by_user": {},
        }
    }
    cog, service = _make_cog(data)
    task = FakeTask()
    cog.queue_cpu_tasks["u1"] = task  # type: ignore[assignment]

    result = asyncio.run(cog._remove_ranked_queue_state("u1"))

    assert result == {"removed_json": True, "removed_sqlite": False, "removed": True}
    assert data["battle"]["queue"] == []
    assert service.removed_queue_users == ["u1"]
    assert task.cancelled is True


def test_remove_pending_friendly_state_clears_json_sqlite_and_task() -> None:
    data = {
        "battle": {
            "queue": [],
            "pending_friendly": {"u2": {"challenger_id": "u1", "target_id": "u2", "expires_at": 999999}},
            "active": {},
            "active_by_user": {},
        }
    }
    cog, service = _make_cog(data)
    task = FakeTask()
    cog.friendly_cpu_tasks["u2"] = task  # type: ignore[assignment]

    result = asyncio.run(cog._remove_pending_friendly_state("u2", cancel_task=True))

    assert result == {"removed_json": True, "removed_sqlite": False, "removed": True}
    assert data["battle"]["pending_friendly"] == {}
    assert service.removed_pending_targets == ["u2"]
    assert task.cancelled is True


def test_recover_active_battles_after_restart_ends_battles_and_syncs_active_users() -> None:
    data = _battle_data()
    battle_id = battle_state.create_battle_state(data, "ranked", "u1", "u2", ["a1"], ["b1"], 1_000)
    data["battle"]["active_by_user"] = {"u1": battle_id, "u2": battle_id, "ghost": "missing"}
    cog, service = _make_cog(data)

    summary = asyncio.run(cog.recover_active_battles_after_restart())

    # After Fix 5, ended battles are moved out of active into recently_ended
    assert battle_id not in data["battle"]["active"]
    recently_ended = data["battle"].get("recently_ended", [])
    battle = next((e for e in recently_ended if isinstance(e, dict) and e.get("battle_id") == battle_id), None)
    assert battle is not None, "ended battle not found in recently_ended"
    assert summary == {"ended": 1, "cleared": 0, "active_by_user": 0, "affected_users": 2}
    assert battle["ended"] is True
    assert battle["reason"] == "abandoned"
    assert data["battle"]["active_by_user"] == {}
    assert service.synced_payloads[-1]["battle"]["active_by_user"] == {}


def test_forfeit_button_uses_interacting_user(monkeypatch) -> None:
    called: list[tuple[object, str]] = []

    async def fake_defer(_interaction) -> None:
        return None

    async def fake_forfeit(interaction, user_id: str) -> None:
        called.append((interaction, user_id))

    monkeypatch.setattr("bot.features.battle_views.defer_component_update", fake_defer)

    cog = SimpleNamespace(forfeit_internal=fake_forfeit, bot=SimpleNamespace(storage=SimpleNamespace(load=lambda: {})))
    button = ForfeitButton(cog, "battle-1", "turn-actor")  # type: ignore[arg-type]
    interaction = SimpleNamespace(user=SimpleNamespace(id=98765))

    asyncio.run(button.callback(interaction))

    assert called == [(interaction, "98765")]
