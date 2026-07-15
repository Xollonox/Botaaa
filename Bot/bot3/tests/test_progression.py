from __future__ import annotations

import json

from neetverse.database import Database
from neetverse.discipline import DisciplineService
from neetverse.mastery import MasteryService
from neetverse.mocks import MockService
from neetverse.planner import PlannerService
from neetverse.profiles import ProfileService
from neetverse.study import StudyService


def ready(tmp_path):
    database = Database(tmp_path / "data.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "One", now=1)
    profiles.update("1", {"target_year": 2027, "current_status": "Class 12", "timezone": "UTC"}, now=2)
    return database, profiles


def test_mock_sections_feed_subject_mastery(tmp_path) -> None:
    database, _ = ready(tmp_path)
    mastery = MasteryService(database)
    result = MockService(database, mastery).record(
        "1", name="Test 1", score=540, max_score=720, now=100,
        sections=[{"subject": "Physics", "score": 135, "max_score": 180}],
    )
    assert result["percentage"] == 75
    physics = next(row for row in mastery.for_user("1") if row["subject"] == "Physics")
    assert physics["score"] == 75


def test_task_requires_approval_then_can_be_completed(tmp_path) -> None:
    database, _ = ready(tmp_path)
    payload = {"title": "Today", "tasks": [{"title": "Read NCERT", "subject": "Biology", "estimated_minutes": 45, "priority": 1}]}
    with database.transaction(immediate=True) as conn:
        conn.execute(
            "INSERT INTO ai_proposals(id,user_id,proposal_type,payload_json,status,created_at) VALUES('p','1','daily_plan',?,'pending',10)",
            (json.dumps(payload),),
        )
    planner = PlannerService(database)
    plan = planner.approve_ai_proposal("1", "p", now=20)
    task = planner.complete_task("1", plan["tasks"][0]["id"][:8], now=30)
    assert task["status"] == "completed"


def test_manual_plan_and_tasks_do_not_require_ai(tmp_path) -> None:
    database, _ = ready(tmp_path)
    planner = PlannerService(database)
    plan = planner.create_manual_plan(
        "1", title="My Biology Week", period_type="weekly",
        starts_on="2026-07-13", ends_on="2026-07-19", now=100,
    )
    task = planner.add_task(
        "1", plan["id"][:8], title="Read genetics", subject="Biology",
        estimated_minutes=60, priority=2, now=101,
    )
    assert task["source"] == "manual"
    assert planner.list_plans("1")[0]["task_count"] == 1


def test_today_plan_is_local_date_aware_and_same_day_plan_is_replaced(tmp_path) -> None:
    database, _ = ready(tmp_path)
    planner = PlannerService(database)
    old = planner.create_manual_plan(
        "1", title="Old", period_type="daily", starts_on="1970-01-02", ends_on="1970-01-02", now=100
    )
    new = planner.create_manual_plan(
        "1", title="New", period_type="daily", starts_on="1970-01-02", ends_on="1970-01-02", now=101
    )

    assert planner.get_plan(old["id"], "1")["status"] == "archived"
    assert planner.active_daily_plan("1", now=100_000)["id"] == new["id"]
    assert planner.active_daily_plan("1", now=200_000) is None


def test_discipline_is_transparent_and_leaderboard_is_opt_in(tmp_path) -> None:
    database, profiles = ready(tmp_path)
    study = StudyService(database)
    # UTC dates 1970-01-02 and 1970-01-03.
    for start in (90_000, 180_000):
        study.start("1", mode="stopwatch", subject="Physics", activity="Questions", now=start)
        study.finish("1", now=start + 3600)
    service = DisciplineService(database)
    result = service.calculate("1", now=200_000)
    assert result["factors"]["consistency"] > 0
    assert result["level_points"] == 120
    assert service.leaderboard(now=200_000) == []

    profiles.update("1", {"leaderboard_visible": True}, now=200_001)
    study.log_manual("1", subject="Biology", activity="Reading", focus_minutes=30, ended_at=199_000)
    leaderboard = service.leaderboard(now=200_000)
    assert leaderboard[0]["display_name"] == "One"
    assert leaderboard[0]["focus_seconds"] == 7200
