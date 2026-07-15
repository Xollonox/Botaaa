from __future__ import annotations

import asyncio
import json

import pytest

from neetverse.ai import AcademicAIService, AIQuotaExceeded, AIResult, OpenRouterClient, _parse_json_object
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


@pytest.mark.parametrize(
    "raw",
    [
        "Here is the plan:\n{\"title\":\"Today\",\"tasks\":[],}\nHope this helps!",
        "{'title': 'Today', 'tasks': [{'title': 'NCERT',}],}",
        "<think>drafting</think> {“title”: “Today”, “tasks”: []}",
    ],
)
def test_json_plan_parser_recovers_common_free_model_formats(raw: str) -> None:
    assert _parse_json_object(raw)["title"] == "Today"


class RepairingClient:
    def __init__(self) -> None:
        self.task_types: list[str] = []

    async def complete(self, **kwargs) -> AIResult:
        self.task_types.append(kwargs["task_type"])
        if kwargs["task_type"] == "daily_plan":
            return AIResult("this is not json", "first/free", "first", 1, 1)
        return AIResult(
            '{"title":"Repaired","tasks":[{"title":"Read NCERT","subject":"Biology",'
            '"chapter":"Genetics","activity":"Reading","estimated_minutes":60,"priority":1}]}',
            "repair/free", "repair", 1, 1,
        )


def test_daily_plan_automatically_repairs_malformed_first_response(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "Student", now=10)
    profiles.update(
        "1",
        {
            "target_year": 2027,
            "current_status": "Class 12",
            "timezone": "UTC",
            "weekday_available_minutes": 120,
            "weekend_available_minutes": 120,
        },
        now=11,
    )
    client = RepairingClient()
    result, payload = asyncio.run(AcademicAIService(database, client).propose_daily_plan("1"))

    assert client.task_types == ["daily_plan", "daily_plan_repair"]
    assert result.model_used == "repair/free"
    assert payload["title"] == "Repaired"
    assert payload["tasks"][0]["estimated_minutes"] == 60


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
