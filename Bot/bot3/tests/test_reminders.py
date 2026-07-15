from __future__ import annotations

from neetverse.database import Database
from neetverse.mastery import MasteryService
from neetverse.profiles import ProfileService
from neetverse.reminders import ReminderService
from neetverse.revision import RevisionService
from neetverse.study import StudyService


def ready(tmp_path):
    database = Database(tmp_path / "data.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "Student", now=1)
    profiles.update(
        "1",
        {
            "target_year": 2027,
            "current_status": "Class 12",
            "timezone": "UTC",
            "pomodoro_focus_minutes": 25,
            "pomodoro_short_break_minutes": 5,
            "pomodoro_long_break_minutes": 20,
            "pomodoro_cycles": 4,
        },
        now=2,
    )
    reminders = ReminderService(database)
    return database, profiles, reminders


def test_reminders_are_private_opt_in_and_claimed_once(tmp_path) -> None:
    database, profiles, reminders = ready(tmp_path)
    StudyService(database, reminders).start(
        "1", mode="countdown", subject="Physics", activity="Questions", planned_minutes=10, now=100
    )
    assert reminders.claim_due(now=700) == []

    profiles.update("1", {"dm_reminders": True}, now=701)
    jobs = reminders.claim_due(now=701)
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "countdown_target"
    assert reminders.claim_due(now=701) == []
    reminders.delivered(jobs[0]["id"], now=702)
    with database.connect() as conn:
        status = conn.execute("SELECT status FROM reminder_jobs WHERE id=?", (jobs[0]["id"],)).fetchone()[0]
    assert status == "delivered"


def test_pausing_and_resuming_replaces_session_deadline(tmp_path) -> None:
    database, profiles, reminders = ready(tmp_path)
    profiles.update("1", {"dm_reminders": True}, now=3)
    study = StudyService(database, reminders)
    study.start(
        "1", mode="pomodoro", subject="Biology", activity="NCERT",
        pomodoro={"focus_minutes": 25, "short_break_minutes": 5, "long_break_minutes": 20, "cycles": 4},
        now=100,
    )
    study.pause("1", now=400)
    assert reminders.claim_due(now=2000) == []
    study.resume("1", now=2000)
    assert reminders.claim_due(now=3199) == []
    assert len(reminders.claim_due(now=3200)) == 1


def test_revision_review_reschedules_same_persistent_job(tmp_path) -> None:
    database, profiles, reminders = ready(tmp_path)
    profiles.update("1", {"dm_reminders": True}, now=3)
    revision = RevisionService(database, MasteryService(database), reminders)
    mistake = revision.add_mistake(
        "1", subject="Chemistry", chapter="Bonding", topic=None,
        category="Conceptual", now=100,
    )
    revision.review("1", mistake["revision_item_id"], "good", now=200)
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT status, due_at FROM reminder_jobs WHERE aggregate_id=?",
            (mistake["revision_item_id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["due_at"] == 200 + 3 * 86400


def test_quiet_hours_defer_delivery(tmp_path) -> None:
    database, profiles, reminders = ready(tmp_path)
    # 2026-01-01 23:00 UTC is inside 22:00–07:00 quiet hours.
    now = 1_767_307_200
    profiles.update(
        "1",
        {"dm_reminders": True, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"},
        now=now,
    )
    with database.transaction(immediate=True) as conn:
        reminders.schedule(
            conn, user_id="1", job_type="custom", due_at=now,
            payload={"message": "Study"}, now=now,
        )
    assert reminders.claim_due(now=now) == []
    with database.connect() as conn:
        due_at = conn.execute("SELECT due_at FROM reminder_jobs").fetchone()[0]
    assert due_at > now
