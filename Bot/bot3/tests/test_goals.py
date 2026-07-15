from __future__ import annotations

from neetverse.database import Database
from neetverse.goals import GoalService
from neetverse.profiles import ProfileService


def test_goals_are_independent_complete_and_cancel_reminders(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    profiles = ProfileService(database)
    for user_id in ("1", "2"):
        profiles.ensure_draft(user_id, user_id, now=1)
        profiles.update(user_id, {"target_year": 2027, "current_status": "Other", "timezone": "UTC"}, now=2)
    service = GoalService(database)
    goal = service.create(
        "1", title="Solve questions", metric="questions", target_value=100,
        unit="questions", due_date="2030-01-01", remind=True, now=100,
    )

    assert service.list("2") == []
    halfway = service.set_progress("1", goal["id"][:8], 50, now=200)
    assert halfway["progress_percent"] == 50
    completed = service.set_progress("1", goal["id"][:8], 100, now=300)
    assert completed["status"] == "completed"
    with database.connect() as conn:
        reminder = conn.execute("SELECT status FROM reminder_jobs WHERE aggregate_id=?", (goal["id"],)).fetchone()
    assert reminder["status"] == "cancelled"
