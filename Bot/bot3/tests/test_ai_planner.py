from __future__ import annotations

import json

import pytest

from neetverse.ai import AIQuotaExceeded, OpenRouterClient, _parse_json_object
from neetverse.database import Database
from neetverse.planner import PlannerError, PlannerService
from neetverse.profiles import ProfileService


@pytest.mark.parametrize("model", ["paid/model", "some/model:free"])
def test_openrouter_client_refuses_any_non_router_model(tmp_path, model: str) -> None:
    database = Database(tmp_path / "data.sqlite3")
    with pytest.raises(ValueError, match="openrouter/free"):
        OpenRouterClient(
            database=database,
            api_key="key",
            base_url="https://openrouter.ai/api/v1",
            model=model,
            timeout_seconds=30,
            daily_global_limit=45,
            daily_user_limit=10,
        )


def test_ai_quota_is_reserved_atomically(tmp_path) -> None:
    client = OpenRouterClient(
        database=Database(tmp_path / "data.sqlite3"),
        api_key="key",
        base_url="https://openrouter.ai/api/v1",
        model="openrouter/free",
        timeout_seconds=30,
        daily_global_limit=3,
        daily_user_limit=2,
    )
    client._reserve_quota("1", "tutor")
    client._reserve_quota("1", "tutor")
    with pytest.raises(AIQuotaExceeded, match="free AI allowance"):
        client._reserve_quota("1", "tutor")


def test_json_plan_parser_handles_fenced_output() -> None:
    value = _parse_json_object('```json\n{"title":"Today","tasks":[]}\n```')
    assert value == {"title": "Today", "tasks": []}


def test_ai_proposal_requires_owner_and_approval_before_tasks_exist(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    profiles = ProfileService(database)
    for user_id in ("1", "2"):
        profiles.ensure_draft(user_id, f"Student {user_id}", now=10)
        profiles.update(
            user_id,
            {"target_year": 2027, "current_status": "Class 12", "timezone": "Asia/Kolkata"},
            now=11,
        )
    payload = {
        "title": "Focused day",
        "tasks": [
            {
                "title": "Mechanics questions",
                "subject": "Physics",
                "chapter": "Laws of Motion",
                "activity": "Question practice",
                "estimated_minutes": 60,
                "priority": 1,
            }
        ],
    }
    with database.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO ai_proposals(id, user_id, proposal_type, payload_json, status, created_at)
            VALUES ('proposal', '1', 'daily_plan', ?, 'pending', 100)
            """,
            (json.dumps(payload),),
        )
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0

    planner = PlannerService(database)
    with pytest.raises(PlannerError, match="no longer available"):
        planner.approve_ai_proposal("2", "proposal", now=200)
    plan = planner.approve_ai_proposal("1", "proposal", now=200)
    assert plan["source"] == "ai_approved"
    assert plan["tasks"][0]["subject"] == "Physics"
    assert planner.active_daily_plan("2") is None
