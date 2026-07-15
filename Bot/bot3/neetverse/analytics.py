"""Read-only academic summaries derived from canonical records."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


class AnalyticsService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def today(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            profile = conn.execute("SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None:
                raise ValueError("Run /start first")
            try:
                zone = ZoneInfo(profile["timezone"]) if profile["timezone"] else ZoneInfo("UTC")
            except ZoneInfoNotFoundError:
                zone = ZoneInfo("UTC")
            local_now = datetime.fromtimestamp(timestamp, zone)
            start = int(local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            end = int((local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp())
            study = conn.execute(
                """
                SELECT COUNT(*) AS sessions, COALESCE(SUM(focus_seconds),0) AS focus_seconds
                FROM study_sessions WHERE user_id=? AND status='completed' AND ended_at>=? AND ended_at<?
                """,
                (str(user_id), start, end),
            ).fetchone()
            practice = conn.execute(
                """
                SELECT COALESCE(SUM(attempted),0) AS attempted, COALESCE(SUM(correct),0) AS correct
                FROM practice_batches WHERE user_id=? AND created_at>=? AND created_at<?
                """,
                (str(user_id), start, end),
            ).fetchone()
            due = int(conn.execute(
                "SELECT COUNT(*) FROM revision_items WHERE user_id=? AND status IN ('due','scheduled') AND due_at<=?",
                (str(user_id), timestamp),
            ).fetchone()[0])
            mastery = conn.execute(
                """
                SELECT subject, score, confidence FROM mastery_snapshots
                WHERE user_id=? AND chapter_key='' ORDER BY subject
                """,
                (str(user_id),),
            ).fetchall()
        attempted, correct = int(practice["attempted"]), int(practice["correct"])
        return {
            "local_date": local_now.date().isoformat(),
            "sessions": int(study["sessions"]),
            "focus_seconds": int(study["focus_seconds"]),
            "questions_attempted": attempted,
            "question_accuracy": round(correct / attempted * 100, 2) if attempted else None,
            "revisions_due": due,
            "mastery": [dict(row) for row in mastery],
        }

    def period(self, user_id: str, *, days: int, now: int | None = None) -> dict[str, Any]:
        if not 1 <= int(days) <= 366:
            raise ValueError("Analytics period must be between 1 and 366 days")
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            profile = conn.execute("SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None or not profile["timezone"]:
                raise ValueError("Set your time zone in /profile first")
            try:
                zone = ZoneInfo(profile["timezone"])
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Your profile time zone is invalid") from exc
            local_now = datetime.fromtimestamp(timestamp, zone)
            first_date = local_now.date() - timedelta(days=int(days) - 1)
            start = int(datetime.combine(first_date, datetime.min.time(), tzinfo=zone).timestamp())
            end = int((datetime.combine(local_now.date(), datetime.min.time(), tzinfo=zone) + timedelta(days=1)).timestamp())
            sessions = conn.execute(
                """
                SELECT subject, focus_seconds, ended_at FROM study_sessions
                WHERE user_id=? AND status='completed' AND ended_at>=? AND ended_at<?
                ORDER BY ended_at
                """,
                (str(user_id), start, end),
            ).fetchall()
            practice = conn.execute(
                """
                SELECT attempted, correct FROM practice_batches
                WHERE user_id=? AND created_at>=? AND created_at<?
                """,
                (str(user_id), start, end),
            ).fetchall()
            revisions = int(conn.execute(
                "SELECT COUNT(*) FROM revision_attempts WHERE user_id=? AND reviewed_at>=? AND reviewed_at<?",
                (str(user_id), start, end),
            ).fetchone()[0])
            mocks = conn.execute(
                "SELECT score, max_score FROM mock_attempts WHERE user_id=? AND attempted_at>=? AND attempted_at<?",
                (str(user_id), start, end),
            ).fetchall()
        by_day: dict[str, int] = {}
        by_subject: dict[str, int] = {}
        for row in sessions:
            day = datetime.fromtimestamp(int(row["ended_at"]), zone).date().isoformat()
            by_day[day] = by_day.get(day, 0) + int(row["focus_seconds"])
            subject = str(row["subject"])
            by_subject[subject] = by_subject.get(subject, 0) + int(row["focus_seconds"])
        attempted = sum(int(row["attempted"]) for row in practice)
        correct = sum(int(row["correct"]) for row in practice)
        focus = sum(by_day.values())
        active_days = sum(1 for value in by_day.values() if value > 0)
        return {
            "days": int(days), "starts_on": first_date.isoformat(), "ends_on": local_now.date().isoformat(),
            "focus_seconds": focus, "sessions": len(sessions), "active_days": active_days,
            "average_focus_per_active_day": round(focus / active_days) if active_days else 0,
            "questions_attempted": attempted,
            "question_accuracy": round(correct / attempted * 100, 2) if attempted else None,
            "revisions_completed": revisions, "mocks_completed": len(mocks),
            "average_mock_percent": round(sum(float(row["score"]) / float(row["max_score"]) * 100 for row in mocks) / len(mocks), 2) if mocks else None,
            "by_day": by_day,
            "by_subject": dict(sorted(by_subject.items(), key=lambda item: item[1], reverse=True)),
        }
