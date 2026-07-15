"""Restart-safe domain-event processing and connected downstream effects."""

from __future__ import annotations

import json
import time
from typing import Any

from .database import Database
from .reminders import ReminderService


class EventProcessor:
    """Process each outbox event once; failures stay pending for retry."""

    def __init__(self, database: Database, reminders: ReminderService | None = None) -> None:
        self.database = database
        self.reminders = reminders or ReminderService(database)

    def process_pending(self, *, limit: int = 100, now: int | None = None) -> dict[str, int]:
        timestamp = int(time.time() if now is None else now)
        processed = failed = 0
        for _ in range(max(1, min(500, int(limit)))):
            outcome = self._process_one(timestamp)
            if outcome == "failed":
                failed += 1
                break
            if outcome == "empty":
                break
            processed += 1
        return {"processed": processed, "failed": failed}

    def _process_one(self, timestamp: int) -> str:
        with self.database.transaction(immediate=True) as conn:
            event = conn.execute(
                "SELECT * FROM domain_events WHERE processed_at IS NULL AND attempts < 5 ORDER BY occurred_at, rowid LIMIT 1"
            ).fetchone()
            if event is None:
                return "empty"
            conn.execute("UPDATE domain_events SET attempts=attempts+1 WHERE id=?", (event["id"],))
            try:
                payload = json.loads(event["payload_json"])
                self._apply_goal_effect(conn, dict(event), payload, timestamp)
            except Exception as exc:
                conn.execute("UPDATE domain_events SET last_error=? WHERE id=?", (str(exc)[:500], event["id"]))
                return "failed"
            conn.execute(
                "UPDATE domain_events SET processed_at=?, last_error=NULL WHERE id=?",
                (timestamp, event["id"]),
            )
        return "processed"

    def _apply_goal_effect(self, conn, event: dict[str, Any], payload: dict[str, Any], timestamp: int) -> None:
        user_id = event.get("user_id")
        if not user_id:
            return
        effects = _goal_effects(str(event["event_type"]), payload)
        if not effects:
            return
        for metric_names, operation, value in effects:
            placeholders = ",".join("?" for _ in metric_names)
            goals = conn.execute(
                f"""
                SELECT * FROM goals
                WHERE user_id=? AND status='active' AND lower(metric) IN ({placeholders})
                  AND created_at <= ?
                """,
                (str(user_id), *metric_names, int(event["occurred_at"])),
            ).fetchall()
            for goal in goals:
                old = float(goal["current_value"])
                current = max(old, value) if operation == "max" else old + value
                completed = current >= float(goal["target_value"])
                conn.execute(
                    """
                    UPDATE goals SET current_value=?, status=?, completed_at=?, updated_at=? WHERE id=?
                    """,
                    (current, "completed" if completed else "active",
                     timestamp if completed else None, timestamp, goal["id"]),
                )
                if completed:
                    self.reminders.cancel_aggregate(conn, str(user_id), "goal", goal["id"])

    def health(self) -> dict[str, int]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN processed_at IS NULL AND attempts < 5 THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN processed_at IS NULL AND attempts >= 5 THEN 1 ELSE 0 END) AS failed
                FROM domain_events
                """
            ).fetchone()
        return {key: int(row[key] or 0) for key in ("total", "pending", "failed")}


def _goal_effects(event_type: str, payload: dict[str, Any]) -> list[tuple[tuple[str, ...], str, float]]:
    if event_type == "StudySessionCompleted":
        return [(("focus_minutes", "study_minutes", "minutes"), "add", float(payload.get("focus_seconds", 0)) / 60)]
    if event_type == "PracticeBatchRecorded":
        return [(("questions", "practice_questions"), "add", float(payload.get("attempted", 0)))]
    if event_type == "RevisionReviewed":
        return [(("revisions", "revision_count"), "add", 1.0)]
    if event_type == "TaskCompleted":
        return [(("tasks", "completed_tasks"), "add", 1.0)]
    if event_type == "MockRecorded":
        score = float(payload.get("score", 0))
        maximum = float(payload.get("max_score", 0))
        percentage = score / maximum * 100 if maximum > 0 else 0
        return [
            (("mocks", "mock_count"), "add", 1.0),
            (("mock_score",), "max", score),
            (("mock_percent", "mock_percentage"), "max", percentage),
        ]
    if event_type == "PageCoverageRecorded":
        return [(("pages", "covered_pages"), "add", float(payload.get("new_unique_pages", 0)))]
    return []
