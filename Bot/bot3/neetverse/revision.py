"""Mistake lifecycle and adaptive revision scheduling."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .database import Database
from .mastery import MasteryService
from .reminders import ReminderService


RESULT_SCORES = {"forgotten": 20.0, "hard": 45.0, "good": 75.0, "easy": 95.0}


class RevisionError(ValueError):
    pass


class RevisionService:
    def __init__(self, database: Database, mastery: MasteryService, reminders: ReminderService | None = None) -> None:
        self.database = database
        self.mastery = mastery
        self.reminders = reminders or ReminderService(database)

    def add_mistake(
        self,
        user_id: str,
        *,
        subject: str,
        chapter: str | None,
        topic: str | None,
        category: str,
        question_reference: str | None = None,
        submitted_answer: str | None = None,
        correct_answer: str | None = None,
        explanation: str | None = None,
        source: str | None = None,
        difficulty: int | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not subject.strip() or not category.strip():
            raise RevisionError("Subject and mistake category are required")
        if difficulty is not None and not 1 <= int(difficulty) <= 5:
            raise RevisionError("Mistake difficulty must be between 1 and 5")
        timestamp = int(time.time() if now is None else now)
        mistake_id = str(uuid.uuid4())
        revision_id = str(uuid.uuid4())
        title = f"Review {subject.strip()} mistake"
        if chapter:
            title += f": {chapter.strip()}"
        with self.database.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone() is None:
                raise RevisionError("Run /start before adding mistakes")
            conn.execute(
                """
                INSERT INTO mistakes(
                    id, user_id, subject, chapter, topic, source, question_reference,
                    submitted_answer, correct_answer, explanation, category, difficulty, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)
                """,
                (
                    mistake_id, str(user_id), subject.strip()[:100], _optional(chapter, 150),
                    _optional(topic, 150), _optional(source, 200), _optional(question_reference, 1000),
                    _optional(submitted_answer, 1000), _optional(correct_answer, 1000),
                    _optional(explanation, 2000), category.strip()[:100], difficulty, timestamp, timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO revision_items(
                    id, user_id, mistake_id, item_type, title, subject, due_at,
                    interval_days, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'mistake', ?, ?, ?, 1, 'scheduled', ?, ?)
                """,
                (revision_id, str(user_id), mistake_id, title[:250], subject.strip()[:100], timestamp + 86400, timestamp, timestamp),
            )
            self.reminders.schedule(
                conn, user_id=str(user_id), job_type="revision_due", due_at=timestamp + 86400,
                payload={"revision_item_id": revision_id, "title": title[:250]},
                aggregate_type="revision_item", aggregate_id=revision_id, now=timestamp,
            )
            self.database.emit_event(
                conn,
                event_type="MistakeCreated",
                aggregate_type="mistake",
                aggregate_id=mistake_id,
                user_id=str(user_id),
                payload={"revision_item_id": revision_id, "subject": subject.strip(), "category": category.strip()},
                occurred_at=timestamp,
            )
        return {"id": mistake_id, "revision_item_id": revision_id, "due_at": timestamp + 86400}

    def mistakes(self, user_id: str, *, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        allowed = {"captured", "classified", "scheduled", "resolved", "reopened"}
        if status and status not in allowed:
            raise RevisionError("Invalid mistake status")
        with self.database.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM mistakes WHERE user_id=? AND status=? ORDER BY updated_at DESC LIMIT ?",
                    (str(user_id), status, max(1, min(100, int(limit)))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mistakes WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                    (str(user_id), max(1, min(100, int(limit)))),
                ).fetchall()
        return [dict(row) for row in rows]

    def due(self, user_id: str, *, now: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM revision_items
                WHERE user_id=? AND status IN ('due','scheduled') AND due_at <= ?
                ORDER BY due_at LIMIT ?
                """,
                (str(user_id), timestamp, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def review(self, user_id: str, revision_item_id: str, result: str, *, now: int | None = None) -> dict[str, Any]:
        outcome = result.strip().lower()
        if outcome not in RESULT_SCORES:
            raise RevisionError("Result must be forgotten, hard, good, or easy")
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            item = conn.execute(
                "SELECT * FROM revision_items WHERE id=? AND user_id=?",
                (revision_item_id, str(user_id)),
            ).fetchone()
            if item is None or item["status"] == "suspended":
                raise RevisionError("Revision item not found")
            previous = int(item["interval_days"])
            next_interval = _next_interval(previous, outcome)
            attempt_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO revision_attempts(
                    id, revision_item_id, user_id, result, reviewed_at,
                    previous_interval_days, next_interval_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (attempt_id, revision_item_id, str(user_id), outcome, timestamp, previous, next_interval),
            )
            conn.execute(
                """
                UPDATE revision_items SET due_at=?, interval_days=?, status='scheduled', updated_at=?
                WHERE id=?
                """,
                (timestamp + next_interval * 86400, next_interval, timestamp, revision_item_id),
            )
            self.reminders.schedule(
                conn, user_id=str(user_id), job_type="revision_due",
                due_at=timestamp + next_interval * 86400,
                payload={"revision_item_id": revision_item_id, "title": item["title"]},
                aggregate_type="revision_item", aggregate_id=revision_item_id, now=timestamp,
            )
            mistake = None
            if item["mistake_id"]:
                mistake = conn.execute("SELECT * FROM mistakes WHERE id=?", (item["mistake_id"],)).fetchone()
                if mistake:
                    status = "resolved" if outcome in {"good", "easy"} else "reopened"
                    conn.execute(
                        "UPDATE mistakes SET status=?, repeat_count=repeat_count+1, updated_at=?, resolved_at=? WHERE id=?",
                        (status, timestamp, timestamp if status == "resolved" else None, mistake["id"]),
                    )
            subject = str(item["subject"] or (mistake["subject"] if mistake else "General"))
            chapter = str(mistake["chapter"] or "") if mistake else None
            conn.execute(
                """
                INSERT INTO mastery_evidence(
                    id, user_id, subject, chapter, evidence_type, score, weight, source_id, occurred_at
                ) VALUES (?, ?, ?, ?, 'revision', ?, 0.3, ?, ?)
                """,
                (str(uuid.uuid4()), str(user_id), subject, chapter or None, RESULT_SCORES[outcome], attempt_id, timestamp),
            )
            self.mastery.recalculate(conn, str(user_id), subject, chapter or None, now=timestamp)
            self.mastery.recalculate(conn, str(user_id), subject, None, now=timestamp)
            self.database.emit_event(
                conn,
                event_type="RevisionReviewed",
                aggregate_type="revision_item",
                aggregate_id=revision_item_id,
                user_id=str(user_id),
                payload={"result": outcome, "next_interval_days": next_interval},
                occurred_at=timestamp,
            )
        return {"id": revision_item_id, "result": outcome, "next_interval_days": next_interval, "due_at": timestamp + next_interval * 86400}

    def resolve_id(self, user_id: str, token: str) -> str:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM revision_items WHERE user_id=? AND id LIKE ? LIMIT 2",
                (str(user_id), f"{token.strip()}%"),
            ).fetchall()
        if not rows:
            raise RevisionError("Revision item not found")
        if len(rows) > 1:
            raise RevisionError("Revision ID is ambiguous; provide more characters")
        return str(rows[0]["id"])


def _next_interval(previous: int, result: str) -> int:
    if result == "forgotten":
        return 1
    if result == "hard":
        return max(1, round(previous * 1.2))
    if result == "good":
        return max(3, round(previous * 2.0))
    return max(7, round(previous * 3.0))


def _optional(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
