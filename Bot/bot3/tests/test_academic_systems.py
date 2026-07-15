from __future__ import annotations

import pytest

from neetverse.coverage import CoverageService
from neetverse.database import Database, LATEST_SCHEMA_VERSION
from neetverse.mastery import MasteryService
from neetverse.practice import PracticeError, PracticeService
from neetverse.profiles import ProfileService
from neetverse.revision import RevisionService


def services(tmp_path):
    database = Database(tmp_path / "data.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "Student", now=1)
    profiles.update("1", {"target_year": 2027, "current_status": "Class 12", "timezone": "Asia/Kolkata"}, now=2)
    mastery = MasteryService(database)
    return database, mastery, PracticeService(database, mastery), RevisionService(database, mastery), CoverageService(database, mastery)


def test_schema_migrates_all_academic_systems(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    with database.connect() as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert version == LATEST_SCHEMA_VERSION
    assert {"curriculum_nodes", "practice_batches", "mistakes", "revision_items", "mastery_snapshots", "mock_attempts", "reminder_jobs"} <= tables


def test_overlapping_page_ranges_are_not_double_counted(tmp_path) -> None:
    _, _, _, _, coverage = services(tmp_path)
    resource = coverage.add_resource(
        "1", name="NCERT Biology", resource_type="book", subject_code="Biology", total_pages=100, now=10
    )
    first = coverage.record_pages("1", resource["id"], page_start=10, page_end=20, activity="Reading", now=20)
    second = coverage.record_pages("1", resource["id"], page_start=18, page_end=30, activity="Reading", now=30)
    revision = coverage.record_pages("1", resource["id"], page_start=10, page_end=15, activity="Revision", now=40)

    assert first["covered_pages"] == 11
    assert second["covered_pages"] == 21
    assert second["new_unique_pages"] == 10
    assert second["coverage_percent"] == 21
    assert revision["covered_pages"] == 6


def test_practice_counts_validate_and_feed_mastery(tmp_path) -> None:
    _, mastery, practice, _, _ = services(tmp_path)
    with pytest.raises(PracticeError, match="must equal"):
        practice.record(
            "1", subject="Physics", chapter="Kinematics", attempted=10,
            correct=8, incorrect=1, skipped=0, now=100,
        )
    result = practice.record(
        "1", subject="Physics", chapter="Kinematics", attempted=20,
        correct=15, incorrect=3, skipped=2, now=100,
    )
    assert result["accuracy"] == 75
    rows = mastery.for_user("1")
    assert any(row["subject"] == "Physics" and row["chapter_key"] == "Kinematics" for row in rows)
    subject = next(row for row in rows if row["subject"] == "Physics" and row["chapter_key"] == "")
    assert subject["score"] == 75
    assert 0 < subject["confidence"] < 1


def test_mistake_creates_revision_and_review_updates_mastery(tmp_path) -> None:
    _, mastery, _, revision, _ = services(tmp_path)
    mistake = revision.add_mistake(
        "1", subject="Chemistry", chapter="Chemical Bonding", topic="Hybridisation",
        category="Conceptual gap", correct_answer="sp3", now=100,
    )
    assert revision.due("1", now=100) == []
    due = revision.due("1", now=100 + 86400)
    assert due[0]["id"] == mistake["revision_item_id"]

    reviewed = revision.review("1", mistake["revision_item_id"], "good", now=100 + 86400)
    assert reviewed["next_interval_days"] == 3
    rows = mastery.for_user("1")
    chemistry = next(row for row in rows if row["subject"] == "Chemistry" and row["chapter_key"] == "")
    assert chemistry["score"] == 75
