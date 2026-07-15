from __future__ import annotations

import pytest

from neetverse.database import Database
from neetverse.profiles import ProfileService
from neetverse.study import StudyError, StudyService


def ready_user(database: Database, user_id: str = "1") -> None:
    profiles = ProfileService(database)
    profiles.ensure_draft(user_id, "Student", now=1)
    profiles.update(
        user_id,
        {"target_year": 2027, "current_status": "Class 12", "timezone": "Asia/Kolkata"},
        now=2,
    )


def test_stopwatch_accounts_focus_pause_and_break_separately(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    ready_user(database)
    study = StudyService(database)
    started = study.start("1", mode="stopwatch", subject="Physics", activity="Questions", now=100)
    assert started["focus_seconds"] == 0

    paused = study.pause("1", now=160)
    assert paused["focus_seconds"] == 60
    assert study.active_for_user("1", now=220)["paused_seconds"] == 60

    study.resume("1", now=220)
    study.start_break("1", now=250)
    during_break = study.active_for_user("1", now=270)
    assert during_break["focus_seconds"] == 90
    assert during_break["paused_seconds"] == 60
    assert during_break["break_seconds"] == 20

    completed = study.finish("1", now=280)
    assert completed["status"] == "completed"
    assert completed["focus_seconds"] == 90
    assert completed["break_seconds"] == 30
    assert study.active_for_user("1", now=300) is None


def test_only_one_active_session_survives_service_restart(tmp_path) -> None:
    path = tmp_path / "data.sqlite3"
    database = Database(path)
    ready_user(database)
    StudyService(database).start("1", mode="stopwatch", subject="Biology", activity="NCERT", now=100)

    restarted = StudyService(Database(path))
    assert restarted.active_for_user("1", now=160)["focus_seconds"] == 60
    with pytest.raises(StudyError, match="already have"):
        restarted.start("1", mode="stopwatch", subject="Chemistry", activity="Lecture", now=160)


def test_pomodoro_phase_progress_is_preserved_while_paused(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    ready_user(database)
    study = StudyService(database)
    config = {"focus_minutes": 25, "short_break_minutes": 5, "long_break_minutes": 20, "cycles": 4}
    study.start("1", mode="pomodoro", subject="Chemistry", activity="Revision", pomodoro=config, now=100)

    break_phase = study.advance_pomodoro("1", now=700)
    assert break_phase["phase"] == "short_break"
    assert break_phase["pomodoro_cycles_completed"] == 1
    assert break_phase["phase_remaining_seconds"] == 300

    paused = study.pause("1", now=760)
    assert paused["phase_remaining_seconds"] == 240
    still_paused = study.active_for_user("1", now=1000)
    assert still_paused["phase_remaining_seconds"] == 240
    assert still_paused["paused_seconds"] == 240

    study.resume("1", now=1000)
    next_focus = study.advance_pomodoro("1", now=1240)
    assert next_focus["phase"] == "focus"
    assert next_focus["phase_remaining_seconds"] == 1500


def test_countdown_and_pomodoro_require_explicit_configuration(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    ready_user(database)
    study = StudyService(database)
    with pytest.raises(StudyError, match="require a duration"):
        study.start("1", mode="countdown", subject="Physics", activity="Lecture", now=100)
    with pytest.raises(StudyError, match="Configure Pomodoro"):
        study.start("1", mode="pomodoro", subject="Physics", activity="Lecture", now=100)


def test_incomplete_profile_cannot_create_ranked_live_time(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    ProfileService(database).ensure_draft("1", "Student")
    with pytest.raises(StudyError, match="Complete"):
        StudyService(database).start("1", mode="stopwatch", subject="Physics", activity="Lecture")


def test_manual_study_log_is_canonical_and_review_guarded(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    ready_user(database)
    service = StudyService(database)
    normal = service.log_manual(
        "1", subject="Biology", activity="NCERT reading", focus_minutes=90, ended_at=10_000
    )
    suspicious = service.log_manual(
        "1", subject="Physics", activity="Problems", focus_minutes=400, ended_at=40_000
    )
    assert normal["mode"] == "manual"
    assert normal["focus_seconds"] == 5_400
    assert normal["status"] == "completed"
    assert suspicious["status"] == "review_required"
