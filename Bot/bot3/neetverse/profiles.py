"""Independent student profile lifecycle."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


EDITABLE_FIELDS = {
    "display_name",
    "target_year",
    "current_status",
    "coaching",
    "timezone",
    "weekday_available_minutes",
    "weekend_available_minutes",
    "current_mock_score",
    "target_score",
    "preferred_language",
    "pomodoro_focus_minutes",
    "pomodoro_short_break_minutes",
    "pomodoro_long_break_minutes",
    "pomodoro_cycles",
    "resources_json",
    "preparation_problems_json",
    "leaderboard_visible",
    "dm_reminders",
    "quiet_hours_start",
    "quiet_hours_end",
}

REQUIRED_ONBOARDING_FIELDS = ("target_year", "current_status", "timezone")


class ProfileValidationError(ValueError):
    pass


class ProfileService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_draft(self, user_id: str, display_name: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO profiles(user_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name, updated_at=excluded.updated_at
                """,
                (str(user_id), display_name.strip() or str(user_id), timestamp, timestamp),
            )
        profile = self.get(user_id)
        if profile is None:
            raise RuntimeError("Profile creation failed")
        return profile

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (str(user_id),)).fetchone()
            if row is None:
                return None
            profile = dict(row)
            progress_rows = conn.execute(
                "SELECT subject_code, progress_note, progress_percent FROM profile_subject_progress WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
        profile["resources"] = json.loads(profile.pop("resources_json") or "[]")
        profile["preparation_problems"] = json.loads(profile.pop("preparation_problems_json") or "[]")
        profile["subject_progress"] = {row["subject_code"]: dict(row) for row in progress_rows}
        profile["leaderboard_visible"] = bool(profile["leaderboard_visible"])
        profile["dm_reminders"] = bool(profile["dm_reminders"])
        return profile

    def update(self, user_id: str, values: dict[str, Any], *, source: str = "user", now: int | None = None) -> dict[str, Any]:
        unknown = set(values) - EDITABLE_FIELDS
        if unknown:
            raise ProfileValidationError(f"Unknown profile fields: {', '.join(sorted(unknown))}")
        normalized = self._normalize(values)
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            current = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (str(user_id),)).fetchone()
            if current is None:
                raise ProfileValidationError("Run /start before editing your profile")
            for field, value in normalized.items():
                old_value = current[field]
                if old_value == value:
                    continue
                conn.execute(f"UPDATE profiles SET {field} = ?, updated_at = ? WHERE user_id = ?", (value, timestamp, str(user_id)))
                conn.execute(
                    """
                    INSERT INTO profile_change_log
                    (id, user_id, field_name, old_value_json, new_value_json, source, changed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), str(user_id), field,
                        json.dumps(old_value), json.dumps(value), source, timestamp,
                    ),
                )
            row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (str(user_id),)).fetchone()
            status = "complete" if all(row[field] is not None and str(row[field]).strip() for field in REQUIRED_ONBOARDING_FIELDS) else "draft"
            conn.execute("UPDATE profiles SET onboarding_status = ?, updated_at = ? WHERE user_id = ?", (status, timestamp, str(user_id)))
            self.database.emit_event(
                conn,
                event_type="ProfileUpdated",
                aggregate_type="profile",
                aggregate_id=str(user_id),
                user_id=str(user_id),
                payload={"fields": sorted(normalized), "onboarding_status": status, "source": source},
                occurred_at=timestamp,
            )
        profile = self.get(user_id)
        if profile is None:
            raise RuntimeError("Profile disappeared after update")
        return profile

    def set_subject_progress(
        self,
        user_id: str,
        subject_code: str,
        *,
        progress_note: str | None,
        progress_percent: float | None,
        now: int | None = None,
    ) -> None:
        subject = subject_code.strip().lower()
        if not subject or len(subject) > 40:
            raise ProfileValidationError("Invalid subject")
        if progress_percent is not None and not 0 <= progress_percent <= 100:
            raise ProfileValidationError("Progress must be between 0 and 100")
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO profile_subject_progress(user_id, subject_code, progress_note, progress_percent, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, subject_code) DO UPDATE SET
                    progress_note=excluded.progress_note,
                    progress_percent=excluded.progress_percent,
                    updated_at=excluded.updated_at
                """,
                (str(user_id), subject, _clean_optional(progress_note, 500), progress_percent, timestamp),
            )

    @staticmethod
    def _normalize(values: dict[str, Any]) -> dict[str, Any]:
        out = dict(values)
        if "timezone" in out and out["timezone"]:
            try:
                ZoneInfo(str(out["timezone"]).strip())
            except ZoneInfoNotFoundError as exc:
                raise ProfileValidationError("Use a valid IANA time zone, for example Asia/Kolkata") from exc
            out["timezone"] = str(out["timezone"]).strip()
        for field in ("target_year", "weekday_available_minutes", "weekend_available_minutes", "pomodoro_focus_minutes", "pomodoro_short_break_minutes", "pomodoro_long_break_minutes", "pomodoro_cycles"):
            if field in out and out[field] not in (None, ""):
                out[field] = int(out[field])
            elif field in out:
                out[field] = None
        if "target_year" in out and out["target_year"] is not None and not 2025 <= out["target_year"] <= 2100:
            raise ProfileValidationError("Target year is outside the supported range")
        for field in ("current_mock_score", "target_score"):
            if field in out and out[field] not in (None, ""):
                out[field] = float(out[field])
            elif field in out:
                out[field] = None
            if field in out and out[field] is not None and not 0 <= out[field] <= 720:
                raise ProfileValidationError("NEET scores must be between 0 and 720")
        for field in ("resources_json", "preparation_problems_json"):
            if field in out and not isinstance(out[field], str):
                out[field] = json.dumps(out[field], ensure_ascii=False)
        for field in ("leaderboard_visible", "dm_reminders"):
            if field in out:
                out[field] = int(bool(out[field]))
        for field in ("quiet_hours_start", "quiet_hours_end"):
            if field in out:
                value = str(out[field] or "").strip()
                if value:
                    parts = value.split(":")
                    if len(parts) != 2 or not all(part.isdigit() for part in parts):
                        raise ProfileValidationError("Quiet hours must use HH:MM")
                    hour, minute = map(int, parts)
                    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                        raise ProfileValidationError("Quiet hours must use 24-hour HH:MM")
                    out[field] = f"{hour:02d}:{minute:02d}"
                else:
                    out[field] = None
        for field in ("display_name", "current_status", "coaching", "preferred_language"):
            if field in out:
                out[field] = _clean_optional(out[field], 200)
        return out


def _clean_optional(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
