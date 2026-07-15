from __future__ import annotations

from neetverse.analytics import AnalyticsService
from neetverse.database import Database
from neetverse.practice import PracticeService
from neetverse.mastery import MasteryService
from neetverse.profiles import ProfileService
from neetverse.study import StudyService


def test_period_analytics_uses_user_timezone_and_canonical_records(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "One", now=1)
    profiles.update("1", {"target_year": 2027, "current_status": "Other", "timezone": "UTC"}, now=2)
    study = StudyService(database)
    study.start("1", mode="stopwatch", subject="Physics", activity="Questions", now=100_000)
    study.finish("1", now=103_600)
    PracticeService(database, MasteryService(database)).record(
        "1", subject="Physics", chapter=None, attempted=20, correct=15, incorrect=5, skipped=0, now=103_600
    )

    result = AnalyticsService(database).period("1", days=7, now=200_000)

    assert result["focus_seconds"] == 3_600
    assert result["questions_attempted"] == 20
    assert result["question_accuracy"] == 75
    assert result["by_subject"] == {"Physics": 3_600}
