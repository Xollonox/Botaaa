from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from neetverse.features.ai import plan_embed
from neetverse.features.lectures import LectureResultsView, lecture_embed
from neetverse.features.profile import profile_embed, public_profile_embed
from neetverse.features.study import session_embed
from neetverse.ui import compact_number, embed, premium_title, progress_bar, sparkline


LECTURES = [
    {
        "video_id": "abc123",
        "title": "NEET Physics Rotation",
        "channel_title": "Study Channel",
        "published_at": "2026-01-02T00:00:00Z",
        "thumbnail_url": "https://img.example/one.jpg",
        "duration_seconds": 3661,
        "view_count": 1_250_000,
        "url": "https://www.youtube.com/watch?v=abc123",
        "selection_reason": "Matched NEET Physics • Rotation • detailed",
    },
    {
        "video_id": "def456",
        "title": "NEET Physics Revision",
        "channel_title": "Revision Channel",
        "published_at": "2026-02-03T00:00:00Z",
        "thumbnail_url": "https://img.example/two.jpg",
        "duration_seconds": 1800,
        "view_count": 900,
        "url": "https://www.youtube.com/watch?v=def456",
        "selection_reason": "Matched NEET Physics • Rotation • revision",
    },
]


def test_premium_embed_and_numeric_ui_helpers() -> None:
    value = embed("Study report", "Evidence-backed progress")

    assert value.title.startswith("⏱️")
    assert value.author.name == "NEETVERSE  •  ACADEMIC COMMAND CENTER"
    assert "FOCUS" in value.footer.text
    assert value.timestamp is not None
    assert progress_bar(75, 100, width=4) == "`▰▰▰▱` **75%**"
    assert progress_bar(150, 100, width=4).endswith("**100%**")
    assert progress_bar(-5, 100, width=4).endswith("**0%**")
    assert compact_number(1_250_000) == "1.2M"
    assert len(sparkline([0, 5, 10])) == 3
    assert premium_title("जीव विज्ञान") == "✨  जीव विज्ञान"


def test_lecture_card_contains_player_metadata_and_thumbnail() -> None:
    value = lecture_embed(LECTURES[0], index=0, total=2, subject="Physics", topic="Rotation")

    assert "RESULT 01/02" in value.description
    assert "1.2M views" in value.description
    assert value.url == LECTURES[0]["url"]
    assert value.thumbnail.url == LECTURES[0]["thumbnail_url"]


def test_lecture_deck_navigation_updates_watch_url() -> None:
    async def scenario() -> None:
        view = LectureResultsView(MagicMock(), 7, LECTURES, "Physics", "Rotation")
        assert view.page_indicator.label == "1/2"
        assert view.previous.disabled is True
        assert view.watch_button.url == LECTURES[0]["url"]

        view.index = 1
        view._sync_controls()
        assert view.page_indicator.label == "2/2"
        assert view.next.disabled is True
        assert view.watch_button.url == LECTURES[1]["url"]
        view.stop()

    asyncio.run(scenario())


def test_core_dashboard_embeds_render_with_real_progress_data() -> None:
    profile = profile_embed(
        {
            "display_name": "Student",
            "onboarding_status": "complete",
            "target_year": 2027,
            "current_status": "Class 12",
            "timezone": "Asia/Kolkata",
            "weekday_available_minutes": 300,
            "weekend_available_minutes": 480,
            "current_mock_score": 540.0,
            "target_score": 650.0,
            "preferred_language": "English",
            "subject_progress": {
                "physics": {"progress_percent": 45.0},
                "chemistry": {"progress_percent": 60.0},
                "biology": {"progress_percent": 75.0},
            },
            "resources": ["NCERT"],
            "preparation_problems": ["Consistency"],
        }
    )
    session = session_embed(
        {
            "status": "running",
            "phase": "focus",
            "subject": "Physics",
            "activity": "Questions",
            "chapter": "Rotation",
            "mode": "pomodoro",
            "focus_seconds": 1200,
            "paused_seconds": 30,
            "break_seconds": 300,
            "phase_remaining_seconds": 1800,
            "pomodoro_focus_minutes": 50,
            "pomodoro_short_break_minutes": 10,
            "pomodoro_long_break_minutes": 20,
            "pomodoro_cycles_completed": 1,
            "pomodoro_cycles_target": 4,
        }
    )
    plan = plan_embed(
        {
            "title": "Focused Day",
            "tasks": [
                {
                    "title": "Rotation practice",
                    "subject": "Physics",
                    "chapter": "Rotation",
                    "estimated_minutes": 60,
                    "priority": 1,
                }
            ],
        }
    )

    assert "PROFILE COMPLETENESS" in profile.description
    assert any("75%" in field.value for field in profile.fields)
    assert "FOCUS PHASE" in session.fields[0].value
    assert "60 min" in plan.description


def test_public_student_card_uses_derived_metrics_without_private_profile_fields() -> None:
    value = public_profile_embed({
        "profile": {
            "display_name": "Student", "target_year": 2027,
            "current_status": "Class 12", "current_mock_score": 540,
            "target_score": 650,
        },
        "streak": {
            "current": 4, "longest": 12, "week_seconds": 18_000,
            "today_seconds": 3_600, "active_days_week": 5,
            "calendar": [{"active": value} for value in (True, True, False, True, True, False, True)],
        },
        "discipline": {
            "tier": "Disciplined", "level": "Aspirant",
            "level_points": 1200, "score": 72,
        },
        "daily_plan": {"completed": 3, "total": 5},
        "syllabus": {
            "subjects": [
                {"subject_code": "physics", "completion": 40},
                {"subject_code": "chemistry", "completion": 50},
                {"subject_code": "biology", "completion": 60},
            ]
        },
        "syllabus_completion": 50,
        "totals": {"questions": 1200, "revisions": 80, "mocks": 9},
    })

    rendered = str(value.to_dict())
    assert "Public Student Card" in rendered
    assert "VERIFIED STREAK" in rendered
    assert "SYLLABUS COMPLETION" in rendered
    assert "timezone" not in rendered.lower()
    assert "coaching" not in rendered.lower()
    assert "books" not in rendered.lower()
