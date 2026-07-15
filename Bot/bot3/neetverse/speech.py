"""Persistent voice preferences and provider-isolated Edge TTS rendering."""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import Database


class SpeechError(RuntimeError):
    """A user-safe speech configuration or rendering failure."""


@dataclass(frozen=True)
class SpeechPreferences:
    voice_name: str
    rate_percent: int
    pitch_hz: int

    @property
    def rate(self) -> str:
        return f"{self.rate_percent:+d}%"

    @property
    def pitch(self) -> str:
        return f"{self.pitch_hz:+d}Hz"


class SpeechPreferenceService:
    """Stores independent per-student speech overrides."""

    def __init__(self, database: Database, *, default_voice: str) -> None:
        self.database = database
        self.default_voice = _validate_voice_name(default_voice)

    def get(self, user_id: str) -> SpeechPreferences:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT voice_name, rate_percent, pitch_hz FROM voice_preferences WHERE user_id=?",
                (str(user_id),),
            ).fetchone()
        if row is None:
            return SpeechPreferences(self.default_voice, 0, 0)
        return SpeechPreferences(
            str(row["voice_name"] or self.default_voice),
            int(row["rate_percent"]),
            int(row["pitch_hz"]),
        )

    def update(
        self,
        user_id: str,
        *,
        voice_name: str | None = None,
        rate_percent: int | None = None,
        pitch_hz: int | None = None,
        now: int | None = None,
    ) -> SpeechPreferences:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            profile = conn.execute(
                "SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)
            ).fetchone()
            if profile is None:
                raise SpeechError("Complete `/start` before saving voice preferences.")
            current = conn.execute(
                "SELECT voice_name, rate_percent, pitch_hz FROM voice_preferences WHERE user_id=?",
                (str(user_id),),
            ).fetchone()
            saved_voice = current["voice_name"] if current else None
            saved_rate = int(current["rate_percent"]) if current else 0
            saved_pitch = int(current["pitch_hz"]) if current else 0

            if voice_name is not None:
                cleaned = voice_name.strip()
                saved_voice = None if cleaned.lower() == "default" else _validate_voice_name(cleaned)
            if rate_percent is not None:
                saved_rate = _bounded(rate_percent, -50, 50, "Speech rate")
            if pitch_hz is not None:
                saved_pitch = _bounded(pitch_hz, -50, 50, "Speech pitch")

            conn.execute(
                """
                INSERT INTO voice_preferences(user_id, voice_name, rate_percent, pitch_hz, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    voice_name=excluded.voice_name,
                    rate_percent=excluded.rate_percent,
                    pitch_hz=excluded.pitch_hz,
                    updated_at=excluded.updated_at
                """,
                (str(user_id), saved_voice, saved_rate, saved_pitch, timestamp),
            )
        return self.get(user_id)


class EdgeSpeechService:
    """Turns bounded plain text into temporary audio without Discord knowledge."""

    def __init__(self, *, timeout_seconds: int, max_characters: int) -> None:
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.max_characters = max(200, min(int(max_characters), 4000))
        self.temp_dir = Path(tempfile.gettempdir()) / "neetverse-tts"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._voice_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._active_files: set[Path] = set()

    async def render(self, text: str, preferences: SpeechPreferences) -> Path:
        spoken = prepare_for_speech(text, max_characters=self.max_characters)
        if not spoken:
            raise SpeechError("There is no readable text to speak.")
        try:
            import edge_tts
        except ImportError as exc:
            raise SpeechError("Edge TTS is not installed on this host.") from exc

        path = self.temp_dir / f"{uuid.uuid4().hex}.mp3"
        self._active_files.add(path)
        try:
            communicator = edge_tts.Communicate(
                spoken,
                preferences.voice_name,
                rate=preferences.rate,
                pitch=preferences.pitch,
            )
            await asyncio.wait_for(communicator.save(str(path)), timeout=self.timeout_seconds)
            if not path.exists() or path.stat().st_size == 0:
                raise SpeechError("Edge TTS returned empty audio.")
            return path
        except SpeechError:
            self.cleanup(path)
            raise
        except asyncio.TimeoutError as exc:
            self.cleanup(path)
            raise SpeechError("Speech generation timed out. Please try again.") from exc
        except Exception as exc:
            self.cleanup(path)
            raise SpeechError("Speech generation is temporarily unavailable.") from exc

    async def voices(self, search: str = "") -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._voice_cache is None or now - self._voice_cache[0] >= 21_600:
            try:
                import edge_tts
            except ImportError as exc:
                raise SpeechError("Edge TTS is not installed on this host.") from exc
            try:
                values = await asyncio.wait_for(edge_tts.list_voices(), timeout=self.timeout_seconds)
            except Exception as exc:
                raise SpeechError("The Edge TTS voice list is temporarily unavailable.") from exc
            self._voice_cache = (now, [dict(value) for value in values])

        needle = search.casefold().strip()
        values = self._voice_cache[1]
        if needle:
            values = [
                value for value in values
                if needle in " ".join(
                    str(value.get(key, ""))
                    for key in ("ShortName", "Locale", "Gender", "FriendlyName")
                ).casefold()
            ]
        return values[:20]

    def cleanup(self, path: Path | None) -> None:
        if path is None:
            return
        self._active_files.discard(path)
        path.unlink(missing_ok=True)

    async def close(self) -> None:
        for path in tuple(self._active_files):
            self.cleanup(path)


def prepare_for_speech(text: str, *, max_characters: int) -> str:
    """Remove Discord/Markdown noise and bound speech duration."""

    value = str(text or "")
    value = re.sub(r"```(?:\w+)?\s*", "", value)
    value = value.replace("```", "").replace("`", "")
    value = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", "link", value)
    value = re.sub(r"<@!?\d+>|<#[0-9]+>|<@&[0-9]+>", "", value)
    value = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s*|[-*+]\s+|>\s*)", "", value)
    value = re.sub(r"[*_~|]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    limit = max(1, int(max_characters))
    if len(value) <= limit:
        return value
    suffix = " The rest is available in the text transcript."
    shortened = value[: max(1, limit - len(suffix))].rstrip()
    boundary = max(shortened.rfind(". "), shortened.rfind("? "), shortened.rfind("! "))
    if boundary >= limit // 2:
        shortened = shortened[: boundary + 1]
    else:
        shortened = shortened.rsplit(" ", 1)[0]
    return f"{shortened}{suffix}"[:limit]


def _validate_voice_name(value: str) -> str:
    cleaned = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,99}", cleaned):
        raise SpeechError("Use an exact Edge TTS voice name from `/voice voices`.")
    return cleaned


def _bounded(value: int, minimum: int, maximum: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SpeechError(f"{label} must be a whole number.") from exc
    if not minimum <= number <= maximum:
        raise SpeechError(f"{label} must be between {minimum} and {maximum}.")
    return number
