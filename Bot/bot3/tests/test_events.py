from __future__ import annotations

from neetverse.database import Database
from neetverse.events import EventProcessor
from neetverse.goals import GoalService
from neetverse.practice import PracticeService
from neetverse.mastery import MasteryService
from neetverse.profiles import ProfileService
from neetverse.study import StudyService


def ready(database: Database) -> None:
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "One", now=1)
    profiles.update("1", {"target_year": 2027, "current_status": "Other", "timezone": "UTC"}, now=2)


def test_domain_events_advance_goals_exactly_once(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    ready(database)
    goals = GoalService(database)
    minutes = goals.create("1", title="Study", metric="focus_minutes", target_value=60, unit="minutes", now=10)
    questions = goals.create("1", title="Questions", metric="questions", target_value=20, unit="questions", now=10)

    study = StudyService(database)
    study.start("1", mode="stopwatch", subject="Physics", activity="Practice", now=20)
    study.finish("1", now=20 + 3600)
    PracticeService(database, MasteryService(database)).record(
        "1", subject="Physics", chapter=None, attempted=20, correct=15, incorrect=5, skipped=0, now=100
    )

    processor = EventProcessor(database)
    first = processor.process_pending(now=200)
    processor.process_pending(now=300)

    assert first["processed"] >= 2
    assert goals.get("1", minutes["id"])["current_value"] == 60
    assert goals.get("1", questions["id"])["current_value"] == 20
    assert goals.get("1", minutes["id"])["status"] == "completed"
    assert processor.health()["pending"] == 0


def test_events_before_goal_creation_do_not_backfill_new_goal(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    ready(database)
    study = StudyService(database)
    study.start("1", mode="stopwatch", subject="Physics", activity="Practice", now=5)
    study.finish("1", now=65)
    goal = GoalService(database).create(
        "1", title="Future study", metric="focus_minutes", target_value=10, unit="minutes", now=100
    )

    EventProcessor(database).process_pending(now=200)

    assert GoalService(database).get("1", goal["id"])["current_value"] == 0
