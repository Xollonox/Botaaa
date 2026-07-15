from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from neetverse.curriculum import CurriculumError, CurriculumService, load_bundled_syllabus
from neetverse.database import Database
from neetverse.news import OfficialNewsService
from neetverse.profiles import ProfileService


def _profile(database: Database, user_id: str, year: int) -> None:
    profiles = ProfileService(database)
    profiles.ensure_draft(user_id, user_id, now=100)
    profiles.update(
        user_id,
        {"target_year": year, "current_status": "Class 12", "timezone": "Asia/Kolkata"},
        now=101,
    )


def test_curriculum_is_selected_by_each_users_target_year(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    service = CurriculumService(database)
    _profile(database, "u2027", 2027)
    _profile(database, "u2028", 2028)
    payload = {
        "exam": "NEET-UG",
        "target_year": 2027,
        "label": "Official NEET UG 2027",
        "source_url": "https://www.nmc.org.in/example.pdf",
        "nodes": [
            {"key": "physics", "node_type": "subject", "subject_code": "physics", "name": "Physics"},
            {"key": "kinematics", "parent_key": "physics", "node_type": "chapter", "subject_code": "physics", "name": "Kinematics"},
        ],
    }
    service.import_version(payload, activate=True, now=200)

    node = service.find_nodes("u2027", "Kinematics")[0]
    result = service.update_progress("u2027", node["id"], "practice_percent", 45, now=300)
    assert result["practice_percent"] == 45
    assert service.summary("u2027")["subjects"][0]["completion"] == pytest.approx(9)
    with pytest.raises(CurriculumError, match="target year"):
        service.summary("u2028")


def test_curriculum_rejects_non_official_source(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    service = CurriculumService(database)
    with pytest.raises(CurriculumError, match="official"):
        service.import_version({
            "exam": "NEET-UG", "target_year": 2027, "label": "Bad",
            "source_url": "https://coaching.example/syllabus",
            "nodes": [{"key": "x", "node_type": "subject", "subject_code": "x", "name": "X"}],
        })


def test_bundled_official_syllabus_is_complete_selectable_and_rolls_up(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    service = CurriculumService(database)
    _profile(database, "u2027", 2027)
    payload = load_bundled_syllabus(Path(__file__).parents[1] / "data" / "neet_ug_2026.json")

    version_id = service.ensure_bundled_version(payload, now=200)
    assert service.ensure_bundled_version(payload, now=201) == version_id
    assert len(payload["nodes"]) == 783
    with pytest.raises(CurriculumError, match="target year"):
        service.summary("u2027")

    selected = service.select_version("u2027", version_id[:8], now=300)
    assert selected["target_year"] == 2026
    physics = service.browse_nodes("u2027", subject="physics")
    assert len(physics["nodes"]) == 20
    measurement = physics["nodes"][0]
    assert measurement["has_children"] is True

    updated = service.update_progress(
        "u2027", measurement["id"], "lecture_percent", 100, now=400
    )
    assert updated["affected_nodes"] == measurement["leaf_count"]
    summary = service.summary("u2027")
    physics_summary = next(row for row in summary["subjects"] if row["subject_code"] == "physics")
    assert 0 < physics_summary["completion"] < 20


class FakeResponse:
    status = 200

    async def text(self) -> str:
        return """
        <nav><a href="https://neet.nta.nic.in/help">NEET Helpdesk</a></nav>
        <table><tr><td>
        <a href="https://neet.nta.nic.in/notice-one.pdf">NEET UG official public notice</a>
        <a href="https://random.example/fake.pdf">NEET leaked dates</a>
        </td></tr></table>
        <a href="/contact-us">Contact us</a>
        """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class FakeSession:
    closed = False

    def get(self, _url: str) -> FakeResponse:
        return FakeResponse()

    async def close(self) -> None:
        self.closed = True


def test_news_ingestion_keeps_only_authority_domains(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    service = OfficialNewsService(database)
    service._session = FakeSession()  # type: ignore[assignment]

    result = asyncio.run(service.sync_all(now=500))
    latest = service.latest()

    assert result["nta_neet"] == 1
    assert result["mcc_ug"] == 0
    assert len(latest) == 1
    assert latest[0]["url"].startswith("https://neet.nta.nic.in/")
