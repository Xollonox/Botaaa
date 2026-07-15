from __future__ import annotations

import json

import pytest

from neetverse.database import Database
from neetverse.profiles import ProfileService, ProfileValidationError
from neetverse.features.profile import ProfileSetupView


def test_new_profile_has_no_assumed_academic_answers(tmp_path) -> None:
    service = ProfileService(Database(tmp_path / "data.sqlite3"))
    profile = service.ensure_draft("1", "Student", now=100)

    assert profile["display_name"] == "Student"
    assert profile["onboarding_status"] == "draft"
    assert profile["target_year"] is None
    assert profile["current_status"] is None
    assert profile["coaching"] is None
    assert profile["timezone"] is None
    assert profile["weekday_available_minutes"] is None
    assert profile["subject_progress"] == {}


def test_required_fields_complete_onboarding_and_are_audited(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    service = ProfileService(database)
    service.ensure_draft("1", "Student", now=100)
    profile = service.update(
        "1",
        {"target_year": 2027, "current_status": "Class 12", "timezone": "Asia/Kolkata"},
        now=110,
    )

    assert profile["onboarding_status"] == "complete"
    with database.connect() as conn:
        changes = conn.execute(
            "SELECT field_name, source FROM profile_change_log WHERE user_id='1' ORDER BY field_name"
        ).fetchall()
        event = conn.execute("SELECT event_type, payload_json FROM domain_events").fetchone()
    assert [row["field_name"] for row in changes] == ["current_status", "target_year", "timezone"]
    assert all(row["source"] == "user" for row in changes)
    assert event["event_type"] == "ProfileUpdated"
    assert json.loads(event["payload_json"])["onboarding_status"] == "complete"


def test_profiles_and_progress_are_isolated_by_user(tmp_path) -> None:
    service = ProfileService(Database(tmp_path / "data.sqlite3"))
    service.ensure_draft("1", "One", now=100)
    service.ensure_draft("2", "Two", now=100)
    service.update("1", {"target_year": 2027, "current_status": "Dropper", "timezone": "UTC"}, now=101)
    service.update("2", {"target_year": 2028, "current_status": "Class 11", "timezone": "Asia/Kolkata"}, now=101)
    service.set_subject_progress("1", "physics", progress_note="Mechanics", progress_percent=25, now=102)

    one = service.get("1")
    two = service.get("2")
    assert one["target_year"] == 2027
    assert two["target_year"] == 2028
    assert one["subject_progress"]["physics"]["progress_percent"] == 25
    assert two["subject_progress"] == {}


def test_invalid_timezone_and_score_are_rejected(tmp_path) -> None:
    service = ProfileService(Database(tmp_path / "data.sqlite3"))
    service.ensure_draft("1", "Student")
    with pytest.raises(ProfileValidationError):
        service.update("1", {"timezone": "Mars/Olympus"})
    with pytest.raises(ProfileValidationError):
        service.update("1", {"target_score": 900})


def test_start_profile_view_has_profile_plus_nine_guide_pages(tmp_path) -> None:
    service = ProfileService(Database(tmp_path / "data.sqlite3"))
    service.ensure_draft("1", "Student")
    view = ProfileSetupView(service, 1)

    assert view.page_total == 10
    assert view.page_indicator.label == "1/10"
    assert view.previous.disabled is True
    assert view.next.disabled is False
