"""Persistent study-session and Pomodoro state machine."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .database import Database
from .reminders import ReminderService


ACTIVE_STATUSES = ("running", "paused", "on_break")
REVIEW_THRESHOLD_SECONDS = 6 * 60 * 60


class StudyError(ValueError):
    pass


class StudyService:
    def __init__(self, database: Database, reminders: ReminderService | None = None) -> None:
        self.database = database
        self.reminders = reminders or ReminderService(database)

    def start(
        self,
        user_id: str,
        *,
        mode: str,
        subject: str,
        activity: str,
        chapter: str | None = None,
        topic: str | None = None,
        planned_minutes: int | None = None,
        pomodoro: dict[str, int] | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if mode not in {"stopwatch", "countdown", "pomodoro"}:
            raise StudyError("Unsupported live study mode")
        if not subject.strip() or not activity.strip():
            raise StudyError("Subject and activity are required")
        if planned_minutes is not None and not 1 <= int(planned_minutes) <= 720:
            raise StudyError("Planned duration must be between 1 and 720 minutes")
        if mode == "countdown" and planned_minutes is None:
            raise StudyError("Countdown sessions require a duration")
        p = self._validate_pomodoro(pomodoro) if mode == "pomodoro" else {}
        timestamp = int(time.time() if now is None else now)
        session_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            profile = conn.execute("SELECT onboarding_status FROM profiles WHERE user_id = ?", (str(user_id),)).fetchone()
            if profile is None or profile["onboarding_status"] != "complete":
                raise StudyError("Complete your /start profile before tracking study")
            existing = conn.execute(
                "SELECT id FROM study_sessions WHERE user_id = ? AND status IN ('running', 'paused', 'on_break')",
                (str(user_id),),
            ).fetchone()
            if existing is not None:
                raise StudyError("You already have an active study session")
            conn.execute(
                """
                INSERT INTO study_sessions (
                    id, user_id, mode, status, phase, subject, chapter, topic, activity,
                    planned_seconds, state_started_at, started_at,
                    pomodoro_focus_minutes, pomodoro_short_break_minutes,
                    pomodoro_long_break_minutes, pomodoro_cycles_target,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'running', 'focus', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, str(user_id), mode, subject.strip()[:100],
                    _optional(chapter, 150), _optional(topic, 150), activity.strip()[:100],
                    int(planned_minutes) * 60 if planned_minutes is not None else None,
                    timestamp, timestamp,
                    p.get("focus_minutes"), p.get("short_break_minutes"),
                    p.get("long_break_minutes"), p.get("cycles"),
                    timestamp, timestamp,
                ),
            )
            if mode == "pomodoro":
                self.reminders.schedule(
                    conn, user_id=str(user_id), job_type="pomodoro_phase",
                    due_at=timestamp + p["focus_minutes"] * 60,
                    payload={"session_id": session_id, "phase": "focus"},
                    aggregate_type="study_session", aggregate_id=session_id, now=timestamp,
                )
            elif mode == "countdown" and planned_minutes is not None:
                self.reminders.schedule(
                    conn, user_id=str(user_id), job_type="countdown_target",
                    due_at=timestamp + int(planned_minutes) * 60,
                    payload={"session_id": session_id, "subject": subject.strip()},
                    aggregate_type="study_session", aggregate_id=session_id, now=timestamp,
                )
            self.database.emit_event(
                conn,
                event_type="StudySessionStarted",
                aggregate_type="study_session",
                aggregate_id=session_id,
                user_id=str(user_id),
                payload={"mode": mode, "subject": subject.strip(), "activity": activity.strip()},
                occurred_at=timestamp,
            )
        return self.get(session_id, now=timestamp)

    def log_manual(
        self,
        user_id: str,
        *,
        subject: str,
        activity: str,
        focus_minutes: int,
        chapter: str | None = None,
        topic: str | None = None,
        notes: str | None = None,
        ended_at: int | None = None,
    ) -> dict[str, Any]:
        minutes = int(focus_minutes)
        if not subject.strip() or not activity.strip():
            raise StudyError("Subject and activity are required")
        if not 1 <= minutes <= 720:
            raise StudyError("Manual focus time must be between 1 and 720 minutes")
        end = int(time.time() if ended_at is None else ended_at)
        seconds = minutes * 60
        start = end - seconds
        status = "review_required" if seconds > REVIEW_THRESHOLD_SECONDS else "completed"
        session_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            profile = conn.execute("SELECT onboarding_status FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None or profile["onboarding_status"] != "complete":
                raise StudyError("Complete your /start profile before tracking study")
            conn.execute(
                """
                INSERT INTO study_sessions(
                    id, user_id, mode, status, phase, subject, chapter, topic, activity,
                    focus_seconds, state_started_at, started_at, ended_at, notes, source,
                    created_at, updated_at
                ) VALUES (?, ?, 'manual', ?, 'focus', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)
                """,
                (session_id, str(user_id), status, subject.strip()[:100], _optional(chapter, 150),
                 _optional(topic, 150), activity.strip()[:100], seconds, end, start, end,
                 _optional(notes, 1000), end, end),
            )
            self.database.emit_event(
                conn,
                event_type="StudySessionReviewRequired" if status == "review_required" else "StudySessionCompleted",
                aggregate_type="study_session", aggregate_id=session_id, user_id=str(user_id),
                payload={"focus_seconds": seconds, "subject": subject.strip(), "activity": activity.strip(), "source": "manual"},
                occurred_at=end,
            )
        return self.get(session_id, now=end)

    def active_for_user(self, user_id: str, *, now: int | None = None) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM study_sessions WHERE user_id = ? AND status IN ('running', 'paused', 'on_break')",
                (str(user_id),),
            ).fetchone()
        return self._project(dict(row), int(time.time() if now is None else now)) if row else None

    def history(self, user_id: str, *, limit: int = 15) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM study_sessions
                WHERE user_id=? AND status NOT IN ('running','paused','on_break')
                ORDER BY COALESCE(ended_at, updated_at) DESC LIMIT ?
                """,
                (str(user_id), max(1, min(50, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, session_id: str, *, now: int | None = None) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise StudyError("Study session not found")
        return self._project(dict(row), int(time.time() if now is None else now))

    def pause(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        return self._transition(user_id, "pause", timestamp)

    def resume(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        return self._transition(user_id, "resume", timestamp)

    def start_break(self, user_id: str, *, long_break: bool = False, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        return self._transition(user_id, "long_break" if long_break else "short_break", timestamp)

    def advance_pomodoro(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        return self._transition(user_id, "advance_pomodoro", timestamp)

    def finish(self, user_id: str, *, notes: str | None = None, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            row = self._active_row(conn, user_id)
            values = self._accrued(dict(row), timestamp)
            final_status = "review_required" if values["focus_seconds"] > REVIEW_THRESHOLD_SECONDS else "completed"
            conn.execute(
                """
                UPDATE study_sessions SET status=?, focus_seconds=?, paused_seconds=?, break_seconds=?,
                    phase_elapsed_seconds=?, ended_at=?, notes=?, updated_at=? WHERE id=?
                """,
                (
                    final_status, values["focus_seconds"], values["paused_seconds"], values["break_seconds"],
                    values["phase_elapsed_seconds"], timestamp, _optional(notes, 1000), timestamp, row["id"],
                ),
            )
            self.reminders.cancel_aggregate(conn, str(user_id), "study_session", row["id"])
            self.database.emit_event(
                conn,
                event_type="StudySessionReviewRequired" if final_status == "review_required" else "StudySessionCompleted",
                aggregate_type="study_session",
                aggregate_id=row["id"],
                user_id=str(user_id),
                payload={
                    "focus_seconds": values["focus_seconds"],
                    "subject": row["subject"],
                    "activity": row["activity"],
                },
                occurred_at=timestamp,
            )
        return self.get(row["id"], now=timestamp)

    def cancel(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            row = self._active_row(conn, user_id)
            conn.execute(
                "UPDATE study_sessions SET status='cancelled', ended_at=?, updated_at=? WHERE id=?",
                (timestamp, timestamp, row["id"]),
            )
            self.reminders.cancel_aggregate(conn, str(user_id), "study_session", row["id"])
        return self.get(row["id"], now=timestamp)

    def _transition(self, user_id: str, action: str, timestamp: int) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as conn:
            row = self._active_row(conn, user_id)
            values = self._accrued(dict(row), timestamp)
            status = row["status"]
            phase = row["phase"]
            resume_phase = row["resume_phase"]
            cycles = int(row["pomodoro_cycles_completed"])
            reset_phase_elapsed = False
            if action == "pause":
                if status == "paused":
                    raise StudyError("Session is already paused")
                resume_phase = phase
                status = "paused"
            elif action == "resume":
                if status != "paused":
                    raise StudyError("Session is not paused")
                phase = resume_phase or "focus"
                status = "running" if phase == "focus" else "on_break"
                resume_phase = None
            elif action in {"short_break", "long_break"}:
                if status != "running" or phase != "focus":
                    raise StudyError("A break can only start during active focus")
                phase = action
                status = "on_break"
                reset_phase_elapsed = True
            elif action == "advance_pomodoro":
                if row["mode"] != "pomodoro" or status == "paused":
                    raise StudyError("No running Pomodoro phase to advance")
                if phase == "focus":
                    cycles += 1
                    cycle_target = max(1, int(row["pomodoro_cycles_target"] or 1))
                    phase = "long_break" if cycles % cycle_target == 0 else "short_break"
                    status = "on_break"
                else:
                    phase = "focus"
                    status = "running"
                reset_phase_elapsed = True
            else:
                raise StudyError("Unknown study transition")
            conn.execute(
                """
                UPDATE study_sessions SET status=?, phase=?, resume_phase=?, focus_seconds=?, paused_seconds=?,
                    break_seconds=?, phase_elapsed_seconds=?, pomodoro_cycles_completed=?, state_started_at=?, updated_at=? WHERE id=?
                """,
                (
                    status, phase, resume_phase, values["focus_seconds"], values["paused_seconds"],
                    values["break_seconds"], 0 if reset_phase_elapsed else values["phase_elapsed_seconds"],
                    cycles, timestamp, timestamp, row["id"],
                ),
            )
            self.reminders.cancel_aggregate(conn, str(user_id), "study_session", row["id"])
            if row["mode"] == "pomodoro" and status != "paused":
                minutes = (
                    int(row["pomodoro_focus_minutes"] or 0)
                    if phase == "focus"
                    else int(row["pomodoro_long_break_minutes"] or 0)
                    if phase == "long_break"
                    else int(row["pomodoro_short_break_minutes"] or 0)
                )
                elapsed = 0 if reset_phase_elapsed else values["phase_elapsed_seconds"]
                self.reminders.schedule(
                    conn, user_id=str(user_id), job_type="pomodoro_phase",
                    due_at=timestamp + max(1, minutes * 60 - elapsed),
                    payload={"session_id": row["id"], "phase": phase},
                    aggregate_type="study_session", aggregate_id=row["id"], now=timestamp,
                )
            elif row["mode"] == "countdown" and status == "running" and row["planned_seconds"]:
                remaining = max(1, int(row["planned_seconds"]) - values["focus_seconds"])
                self.reminders.schedule(
                    conn, user_id=str(user_id), job_type="countdown_target",
                    due_at=timestamp + remaining,
                    payload={"session_id": row["id"], "subject": row["subject"]},
                    aggregate_type="study_session", aggregate_id=row["id"], now=timestamp,
                )
        return self.get(row["id"], now=timestamp)

    @staticmethod
    def _active_row(conn, user_id: str):
        row = conn.execute(
            "SELECT * FROM study_sessions WHERE user_id=? AND status IN ('running', 'paused', 'on_break')",
            (str(user_id),),
        ).fetchone()
        if row is None:
            raise StudyError("You do not have an active study session")
        return row

    @staticmethod
    def _accrued(row: dict[str, Any], timestamp: int) -> dict[str, int]:
        elapsed = max(0, timestamp - int(row["state_started_at"]))
        focus = int(row["focus_seconds"])
        paused = int(row["paused_seconds"])
        breaks = int(row["break_seconds"])
        phase_elapsed = int(row["phase_elapsed_seconds"])
        if row["status"] == "paused":
            paused += elapsed
        elif row["status"] == "on_break":
            breaks += elapsed
            phase_elapsed += elapsed
        elif row["status"] == "running" and row["phase"] == "focus":
            focus += elapsed
            phase_elapsed += elapsed
        return {
            "focus_seconds": focus,
            "paused_seconds": paused,
            "break_seconds": breaks,
            "phase_elapsed_seconds": phase_elapsed,
        }

    @classmethod
    def _project(cls, row: dict[str, Any], timestamp: int) -> dict[str, Any]:
        if row["status"] in ACTIVE_STATUSES:
            row.update(cls._accrued(row, timestamp))
        planned = row.get("planned_seconds")
        row["remaining_seconds"] = max(0, int(planned) - int(row["focus_seconds"])) if planned else None
        if row["mode"] == "pomodoro" and row["status"] in ACTIVE_STATUSES:
            if row["phase"] == "focus":
                phase_total = int(row["pomodoro_focus_minutes"] or 0) * 60
            elif row["phase"] == "long_break":
                phase_total = int(row["pomodoro_long_break_minutes"] or 0) * 60
            else:
                phase_total = int(row["pomodoro_short_break_minutes"] or 0) * 60
            row["phase_remaining_seconds"] = max(0, phase_total - int(row["phase_elapsed_seconds"]))
        return row

    @staticmethod
    def _validate_pomodoro(config: dict[str, int] | None) -> dict[str, int]:
        if not config:
            raise StudyError("Configure Pomodoro preferences in your profile first")
        limits = {
            "focus_minutes": (1, 240),
            "short_break_minutes": (1, 120),
            "long_break_minutes": (1, 180),
            "cycles": (1, 20),
        }
        out: dict[str, int] = {}
        for key, (low, high) in limits.items():
            value = config.get(key)
            if value is None or not low <= int(value) <= high:
                raise StudyError(f"Invalid Pomodoro {key.replace('_', ' ')}")
            out[key] = int(value)
        return out


def _optional(value: str | None, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
