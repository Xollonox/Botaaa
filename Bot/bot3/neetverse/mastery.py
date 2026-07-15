"""Deterministic, versioned mastery calculation from academic evidence."""

from __future__ import annotations

import time
from typing import Any

from .database import Database


FORMULA_VERSION = 1


class MasteryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def recalculate(self, conn, user_id: str, subject: str, chapter: str | None, *, now: int) -> dict[str, float]:
        if chapter:
            rows = conn.execute(
                """
                SELECT score, weight, occurred_at FROM mastery_evidence
                WHERE user_id=? AND lower(subject)=lower(?) AND lower(COALESCE(chapter,''))=lower(?)
                ORDER BY occurred_at DESC LIMIT 100
                """,
                (str(user_id), subject, chapter),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT score, weight, occurred_at FROM mastery_evidence
                WHERE user_id=? AND lower(subject)=lower(?)
                ORDER BY occurred_at DESC LIMIT 200
                """,
                (str(user_id), subject),
            ).fetchall()
        weighted_score = 0.0
        effective_weight = 0.0
        for row in rows:
            age_days = max(0.0, (now - int(row["occurred_at"])) / 86400)
            recency = max(0.30, 1.0 - min(age_days, 90.0) / 128.6)
            weight = float(row["weight"]) * recency
            weighted_score += float(row["score"]) * weight
            effective_weight += weight
        score = weighted_score / effective_weight if effective_weight else 0.0
        confidence = min(1.0, effective_weight / 5.0)
        conn.execute(
            """
            INSERT INTO mastery_snapshots(user_id, subject, chapter_key, score, confidence, formula_version, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, subject, chapter_key) DO UPDATE SET
                score=excluded.score, confidence=excluded.confidence,
                formula_version=excluded.formula_version, updated_at=excluded.updated_at
            """,
            (str(user_id), subject, chapter or "", round(score, 2), round(confidence, 4), FORMULA_VERSION, now),
        )
        return {"score": round(score, 2), "confidence": round(confidence, 4)}

    def for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mastery_snapshots WHERE user_id=? ORDER BY subject, chapter_key",
                (str(user_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def rebuild_user(self, user_id: str, *, now: int | None = None) -> None:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            keys = conn.execute(
                "SELECT DISTINCT subject, chapter FROM mastery_evidence WHERE user_id=?",
                (str(user_id),),
            ).fetchall()
            for key in keys:
                self.recalculate(conn, str(user_id), key["subject"], key["chapter"], now=timestamp)
            for subject in {row["subject"] for row in keys}:
                self.recalculate(conn, str(user_id), subject, None, now=timestamp)
