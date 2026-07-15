"""Independent, measurable student goals with optional reminders."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database
from .reminders import ReminderService


class GoalError(ValueError):
    pass


class GoalService:
    def __init__(self, database: Database, reminders: ReminderService | None = None) -> None:
        self.database = database
        self.reminders = reminders or ReminderService(database)

    def create(
        self,
        user_id: str,
        *,
        title: str,
        metric: str,
        target_value: float,
        unit: str,
        subject: str | None = None,
        due_date: str | None = None,
        remind: bool = False,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not title.strip() or not metric.strip() or not unit.strip():
            raise GoalError("Goal title, metric, and unit are required")
        target = float(target_value)
        if not 0 < target <= 10_000_000:
            raise GoalError("Goal target must be greater than zero")
        timestamp = int(time.time() if now is None else now)
        goal_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            profile = conn.execute("SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None:
                raise GoalError("Run /start before creating goals")
            due_at = _due_timestamp(due_date, profile["timezone"]) if due_date else None
            if due_at is not None and due_at <= timestamp:
                raise GoalError("Goal due date must be in the future")
            conn.execute(
                """
                INSERT INTO goals(id, user_id, title, subject, metric, target_value,
                    unit, due_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (goal_id, str(user_id), title.strip()[:200], _optional(subject, 100),
                 metric.strip()[:100], target, unit.strip()[:50], due_at, timestamp, timestamp),
            )
            if remind and due_at is not None:
                self.reminders.schedule(
                    conn, user_id=str(user_id), job_type="goal_due", due_at=due_at,
                    payload={"goal_id": goal_id, "title": title.strip()[:200]},
                    aggregate_type="goal", aggregate_id=goal_id, now=timestamp,
                )
            self.database.emit_event(
                conn, event_type="GoalCreated", aggregate_type="goal", aggregate_id=goal_id,
                user_id=str(user_id), payload={"metric": metric.strip(), "target_value": target}, occurred_at=timestamp,
            )
        return self.get(user_id, goal_id)

    def list(self, user_id: str, *, include_finished: bool = False) -> list[dict[str, Any]]:
        where = "user_id=?" if include_finished else "user_id=? AND status='active'"
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM goals WHERE {where} ORDER BY due_at IS NULL, due_at, created_at DESC LIMIT 25",
                (str(user_id),),
            ).fetchall()
        return [_project(dict(row)) for row in rows]

    def get(self, user_id: str, token: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE user_id=? AND id LIKE ? LIMIT 2",
                (str(user_id), f"{token.strip()}%"),
            ).fetchall()
        if not rows:
            raise GoalError("Goal not found")
        if len(rows) > 1:
            raise GoalError("Goal ID is ambiguous; provide more characters")
        return _project(dict(rows[0]))

    def set_progress(self, user_id: str, token: str, value: float, *, now: int | None = None) -> dict[str, Any]:
        current = float(value)
        if current < 0 or current > 10_000_000:
            raise GoalError("Goal progress cannot be negative")
        timestamp = int(time.time() if now is None else now)
        goal = self.get(user_id, token)
        if goal["status"] != "active":
            raise GoalError("Only active goals can be updated")
        completed = current >= float(goal["target_value"])
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                """
                UPDATE goals SET current_value=?, status=?, completed_at=?, updated_at=?
                WHERE id=? AND user_id=?
                """,
                (current, "completed" if completed else "active", timestamp if completed else None,
                 timestamp, goal["id"], str(user_id)),
            )
            if completed:
                self.reminders.cancel_aggregate(conn, str(user_id), "goal", goal["id"])
            self.database.emit_event(
                conn, event_type="GoalCompleted" if completed else "GoalProgressUpdated",
                aggregate_type="goal", aggregate_id=goal["id"], user_id=str(user_id),
                payload={"current_value": current, "target_value": goal["target_value"]}, occurred_at=timestamp,
            )
        return self.get(user_id, goal["id"])

    def cancel(self, user_id: str, token: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        goal = self.get(user_id, token)
        if goal["status"] != "active":
            raise GoalError("Only active goals can be cancelled")
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE goals SET status='cancelled', updated_at=? WHERE id=? AND user_id=?",
                (timestamp, goal["id"], str(user_id)),
            )
            self.reminders.cancel_aggregate(conn, str(user_id), "goal", goal["id"])
        return self.get(user_id, goal["id"])


def _due_timestamp(value: str, timezone_name: str | None) -> int:
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else None
        if zone is None:
            raise GoalError("Set your time zone before using goal due dates")
        due_date = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ZoneInfoNotFoundError as exc:
        raise GoalError("Your profile time zone is invalid") from exc
    except ValueError as exc:
        raise GoalError("Goal due date must use YYYY-MM-DD") from exc
    return int(datetime.combine(due_date, datetime.max.time(), tzinfo=zone).timestamp())


def _project(row: dict[str, Any]) -> dict[str, Any]:
    target = float(row["target_value"])
    row["progress_percent"] = round(min(100.0, float(row["current_value"]) / target * 100), 2)
    return row


def _optional(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
