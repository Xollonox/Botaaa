from __future__ import annotations

import pytest

from neetverse.database import Database
from neetverse.privacy import PrivacyService
from neetverse.profiles import ProfileService
from neetverse.speech import (
    SpeechError,
    SpeechPreferenceService,
    prepare_for_speech,
)


def test_speech_preferences_are_independent_and_exported(tmp_path) -> None:
    database = Database(tmp_path / "speech.sqlite3")
    profiles = ProfileService(database)
    profiles.ensure_draft("1", "First", now=1)
    profiles.ensure_draft("2", "Second", now=1)
    service = SpeechPreferenceService(database, default_voice="en-IN-NeerjaNeural")

    assert service.get("1").voice_name == "en-IN-NeerjaNeural"
    changed = service.update(
        "1", voice_name="hi-IN-SwaraNeural", rate_percent=12, pitch_hz=-4, now=2
    )
    assert changed.voice_name == "hi-IN-SwaraNeural"
    assert changed.rate == "+12%"
    assert changed.pitch == "-4Hz"
    assert service.get("2").rate_percent == 0

    exported = PrivacyService(database).export("1")
    assert exported["data"]["voice_preferences"][0]["voice_name"] == "hi-IN-SwaraNeural"

    reset = service.update("1", voice_name="default", now=3)
    assert reset.voice_name == "en-IN-NeerjaNeural"
    assert reset.rate_percent == 12


def test_speech_preferences_require_profile_and_validate_voice(tmp_path) -> None:
    service = SpeechPreferenceService(
        Database(tmp_path / "speech.sqlite3"), default_voice="en-IN-NeerjaNeural"
    )
    with pytest.raises(SpeechError, match="/start"):
        service.update("missing", rate_percent=10)

    ProfileService(service.database).ensure_draft("1", "Student", now=1)
    with pytest.raises(SpeechError, match="exact Edge TTS voice"):
        service.update("1", voice_name="not a valid voice")


def test_prepare_for_speech_removes_discord_markdown_and_bounds_text() -> None:
    raw = "## Result\n- **Read** [NCERT](https://example.com) <@123> " + ("carefully " * 80)
    spoken = prepare_for_speech(raw, max_characters=220)

    assert "**" not in spoken
    assert "https://" not in spoken
    assert "<@123>" not in spoken
    assert "Read NCERT" in spoken
    assert len(spoken) <= 220
    assert spoken.endswith("The rest is available in the text transcript.")
