"""Question-practice batches feeding deterministic mastery evidence."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .database import Database
from .mastery import MasteryService


class PracticeError(ValueError):
    pass


class PracticeService:
    def __init__(self, database: Database, mastery: MasteryService) -> None:
        self.database = database
        self.mastery = mastery

    def record(
        self,
        user_id: str,
        *,
        subject: str,
        chapter: str | None,
        attempted: int,
        correct: int,
        incorrect: int,
        skipped: int,
        source: str | None = None,
        duration_minutes: int | None = None,
        session_id: str | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        values = [int(attempted), int(correct), int(incorrect), int(skipped)]
        attempted, correct, incorrect, skipped = values
        if attempted <= 0 or min(correct, incorrect, skipped) < 0:
            raise PracticeError("Question counts must be positive")
        if correct + incorrect + skipped != attempted:
            raise PracticeError("Correct + incorrect + skipped must equal attempted")
        if duration_minutes is not None and not 0 <= int(duration_minutes) <= 1440:
            raise PracticeError("Practice duration is invalid")
        if not subject.strip():
            raise PracticeError("Subject is required")
        timestamp = int(time.time() if now is None else now)
        batch_id = str(uuid.uuid4())
        accuracy = correct / attempted * 100
        evidence_weight = min(1.0, attempted / 50)
        with self.database.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone() is None:
                raise PracticeError("Run /start before logging practice")
            conn.execute(
                """
                INSERT INTO practice_batches(
                    id, user_id, session_id, subject, chapter, source, attempted, correct,
                    incorrect, skipped, duration_seconds, accuracy, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id, str(user_id), session_id, subject.strip()[:100], _optional(chapter, 150),
                    _optional(source, 200), attempted, correct, incorrect, skipped,
                    int(duration_minutes) * 60 if duration_minutes is not None else None,
                    accuracy, timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO mastery_evidence(
                    id, user_id, subject, chapter, evidence_type, score, weight, source_id, occurred_at
                ) VALUES (?, ?, ?, ?, 'practice', ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), str(user_id), subject.strip()[:100], _optional(chapter, 150), accuracy, evidence_weight, batch_id, timestamp),
            )
            chapter_mastery = self.mastery.recalculate(conn, str(user_id), subject.strip()[:100], _optional(chapter, 150), now=timestamp)
            subject_mastery = self.mastery.recalculate(conn, str(user_id), subject.strip()[:100], None, now=timestamp)
            self.database.emit_event(
                conn,
                event_type="PracticeBatchRecorded",
                aggregate_type="practice_batch",
                aggregate_id=batch_id,
                user_id=str(user_id),
                payload={"attempted": attempted, "accuracy": round(accuracy, 2), "subject": subject.strip()},
                occurred_at=timestamp,
            )
        return {
            "id": batch_id,
            "attempted": attempted,
            "correct": correct,
            "incorrect": incorrect,
            "skipped": skipped,
            "accuracy": round(accuracy, 2),
            "chapter_mastery": chapter_mastery,
            "subject_mastery": subject_mastery,
        }


def _optional(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
