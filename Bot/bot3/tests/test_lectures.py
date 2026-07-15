from __future__ import annotations

import asyncio
import json

import pytest

from neetverse.database import Database
from neetverse.lectures import LectureError, LectureService, _iso_duration_seconds
from neetverse.profiles import ProfileService


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def text(self) -> str:
        return json.dumps(self.payload)


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []

    def get(self, url: str, **_):
        self.calls.append(url)
        if url.endswith("/search"):
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": {"videoId": "abc123"},
                            "snippet": {
                                "title": "Cell Cycle for NEET",
                                "channelTitle": "Teacher",
                                "description": "NCERT-focused lecture",
                                "publishedAt": "2026-01-01T00:00:00Z",
                                "thumbnails": {"medium": {"url": "https://img.example/x.jpg"}},
                            },
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "items": [
                    {
                        "id": "abc123",
                        "contentDetails": {"duration": "PT1H2M3S"},
                        "statistics": {"viewCount": "12345"},
                        "status": {"privacyStatus": "public", "embeddable": True},
                    }
                ]
            }
        )


def test_youtube_duration_parser() -> None:
    assert _iso_duration_seconds("PT1H2M3S") == 3723
    assert _iso_duration_seconds("PT15M") == 900
    assert _iso_duration_seconds("invalid") is None


def test_search_uses_two_api_reads_then_six_hour_cache(tmp_path) -> None:
    service = LectureService(Database(tmp_path / "data.sqlite3"), api_key="key", base_url="https://youtube.test/v3")
    fake = FakeSession()
    service._session = fake
    first = asyncio.run(service.search(subject="Biology", topic="Cell cycle", language="English", now=100))
    second = asyncio.run(service.search(subject="Biology", topic="Cell cycle", language="English", now=101))

    assert first == second
    assert first[0]["duration_seconds"] == 3723
    assert first[0]["view_count"] == 12345
    assert len(fake.calls) == 2


def test_search_requires_configuration_and_saves_per_user(tmp_path) -> None:
    database = Database(tmp_path / "data.sqlite3")
    service = LectureService(database, api_key="", base_url="https://youtube.test/v3")
    with pytest.raises(LectureError, match="not configured"):
        asyncio.run(service.search(subject="Physics", topic="Kinematics"))

    profiles = ProfileService(database)
    profiles.ensure_draft("1", "One", now=1)
    saved = service.save(
        "1",
        {"video_id": "abc", "title": "Lecture", "channel_title": "Teacher", "url": "https://youtube.com/watch?v=abc"},
        subject="Physics",
        topic="Kinematics",
        now=2,
    )
    assert saved["video_id"] == "abc"
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM saved_lectures WHERE user_id='1'").fetchone()[0] == 1
