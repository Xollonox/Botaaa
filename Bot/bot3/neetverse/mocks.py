"""Mock-test records and mastery evidence."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .database import Database
from .mastery import MasteryService


class MockError(ValueError):
    pass


class MockService:
    def __init__(self, database: Database, mastery: MasteryService) -> None:
        self.database = database
        self.mastery = mastery

    def record(
        self,
        user_id: str,
        *,
        name: str,
        score: float,
        max_score: float = 720,
        scope: str = "full",
        source: str | None = None,
        correct: int | None = None,
        incorrect: int | None = None,
        skipped: int | None = None,
        duration_minutes: int | None = None,
        sections: list[dict[str, Any]] | None = None,
        attempted_at: int | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not name.strip() or not scope.strip():
            raise MockError("Mock name and scope are required")
        if float(max_score) <= 0 or not 0 <= float(score) <= float(max_score):
            raise MockError("Mock score is outside its maximum")
        for value in (correct, incorrect, skipped, duration_minutes):
            if value is not None and int(value) < 0:
                raise MockError("Mock counts and duration cannot be negative")
        supplied_counts = (correct, incorrect, skipped)
        if any(value is not None for value in supplied_counts) and not all(value is not None for value in supplied_counts):
            raise MockError("Provide correct, incorrect, and skipped counts together")
        timestamp = int(time.time() if now is None else now)
        attempt_time = int(timestamp if attempted_at is None else attempted_at)
        mock_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone() is None:
                raise MockError("Run /start before recording mocks")
            conn.execute(
                """
                INSERT INTO mock_attempts(
                    id, user_id, name, source, scope, score, max_score, correct,
                    incorrect, skipped, duration_seconds, attempted_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mock_id, str(user_id), name.strip()[:200], _optional(source, 200), scope.strip()[:100],
                    float(score), float(max_score), correct, incorrect, skipped,
                    int(duration_minutes) * 60 if duration_minutes is not None else None,
                    attempt_time, timestamp,
                ),
            )
            normalized_sections: list[dict[str, Any]] = []
            for section in sections or []:
                subject = str(section.get("subject", "")).strip()
                section_max = float(section.get("max_score", 0) or 0)
                section_score = float(section.get("score", 0) or 0)
                if not subject or section_max <= 0 or not 0 <= section_score <= section_max:
                    raise MockError("A mock section is invalid")
                section_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO mock_sections(id, mock_id, subject, score, max_score, correct, incorrect, skipped, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        section_id, mock_id, subject[:100], section_score, section_max,
                        section.get("correct"), section.get("incorrect"), section.get("skipped"),
                        int(section["duration_minutes"]) * 60 if section.get("duration_minutes") is not None else None,
                    ),
                )
                percentage = section_score / section_max * 100
                conn.execute(
                    """
                    INSERT INTO mastery_evidence(
                        id, user_id, subject, evidence_type, score, weight, source_id, occurred_at
                    ) VALUES (?, ?, ?, 'mock', ?, 0.8, ?, ?)
                    """,
                    (str(uuid.uuid4()), str(user_id), subject[:100], percentage, section_id, attempt_time),
                )
                self.mastery.recalculate(conn, str(user_id), subject[:100], None, now=timestamp)
                normalized_sections.append({"subject": subject[:100], "score": section_score, "max_score": section_max, "percentage": round(percentage, 2)})
            self.database.emit_event(
                conn,
                event_type="MockRecorded",
                aggregate_type="mock_attempt",
                aggregate_id=mock_id,
                user_id=str(user_id),
                payload={"score": float(score), "max_score": float(max_score), "scope": scope.strip()},
                occurred_at=timestamp,
            )
        return {
            "id": mock_id,
            "name": name.strip(),
            "score": float(score),
            "max_score": float(max_score),
            "percentage": round(float(score) / float(max_score) * 100, 2),
            "sections": normalized_sections,
        }

    def history(self, user_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT *, ROUND(score / max_score * 100, 2) AS percentage
                FROM mock_attempts WHERE user_id=?
                ORDER BY attempted_at DESC LIMIT ?
                """,
                (str(user_id), max(1, min(25, int(limit)))),
            ).fetchall()
        history = [dict(row) for row in rows]
        chronological = list(reversed(history))
        for index, row in enumerate(chronological):
            row["score_change"] = None if index == 0 else round(float(row["percentage"]) - float(chronological[index - 1]["percentage"]), 2)
        return history


def _optional(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
