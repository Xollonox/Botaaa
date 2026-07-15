from __future__ import annotations

from neetverse.database import Database
from neetverse.profiles import ProfileService
from neetverse.streaks import StreakService
from neetverse.study import StudyService


def test_streak_uses_local_days_and_excludes_manual_logs(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "Student", now=1)
    profiles.update(
        "1",
        {"target_year": 2027, "current_status": "Class 12", "timezone": "UTC"},
        now=2,
    )
    study = StudyService(database)
    day = 1_767_225_600  # 2026-01-01 00:00 UTC
    for offset in (0, 1, 3):
        started = day + offset * 86_400 + 3_600
        study.start("1", mode="stopwatch", subject="Physics", activity="Questions", now=started)
        study.finish("1", now=started + 1_800)
    study.log_manual(
        "1", subject="Biology", activity="Reading", focus_minutes=120,
        ended_at=day + 2 * 86_400 + 3_600,
    )

    result = StreakService(database).calculate("1", now=day + 4 * 86_400 + 12 * 3_600)

    assert result["current"] == 1  # yesterday counts while today is still open
    assert result["longest"] == 2
    assert result["active_days_week"] == 3
    assert result["week_seconds"] == 5_400
    assert result["total_verified_seconds"] == 5_400
