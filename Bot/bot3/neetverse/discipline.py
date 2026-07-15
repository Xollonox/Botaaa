"""Transparent study level, discipline tier and opt-in rankings."""

from __future__ import annotations

import json
import math
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


FORMULA_VERSION = 1
LEVELS = (
    (0, "Foundation"),
    (300, "Learner"),
    (1000, "Aspirant"),
    (2500, "Consistent Aspirant"),
    (5000, "NEET Challenger"),
    (10000, "NEET Achiever"),
    (20000, "Ranker"),
    (40000, "Top Ranker"),
)


class DisciplineService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def calculate(self, user_id: str, *, now: int | None = None, persist: bool = True) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            profile = conn.execute("SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
        if profile is None:
            raise ValueError("Profile not found")
        try:
            zone = ZoneInfo(profile["timezone"]) if profile["timezone"] else ZoneInfo("UTC")
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        local_now = datetime.fromtimestamp(timestamp, zone)
        period_end = local_now.date()
        period_start = period_end - timedelta(days=6)
        start_ts = int(datetime.combine(period_start, datetime.min.time(), tzinfo=zone).timestamp())

        with self.database.connect() as conn:
            sessions = conn.execute(
                """
                SELECT subject, focus_seconds, ended_at FROM study_sessions
                WHERE user_id=? AND status='completed' AND ended_at>=? AND ended_at<=?
                """,
                (str(user_id), start_ts, timestamp),
            ).fetchall()
            tasks = conn.execute(
                "SELECT status FROM tasks WHERE user_id=? AND created_at>=? AND created_at<=?",
                (str(user_id), start_ts, timestamp),
            ).fetchall()
            overdue = int(conn.execute(
                "SELECT COUNT(*) FROM revision_items WHERE user_id=? AND status IN ('due','scheduled') AND due_at<?",
                (str(user_id), timestamp),
            ).fetchone()[0])
            totals = conn.execute(
                """
                SELECT
                    COALESCE((SELECT SUM(focus_seconds)/60 FROM study_sessions WHERE user_id=? AND status='completed'),0) AS focus_minutes,
                    COALESCE((SELECT SUM(attempted) FROM practice_batches WHERE user_id=?),0) AS questions,
                    COALESCE((SELECT COUNT(*) FROM revision_attempts WHERE user_id=?),0) AS revisions,
                    COALESCE((SELECT COUNT(*) FROM mock_attempts WHERE user_id=?),0) AS mocks
                """,
                (str(user_id), str(user_id), str(user_id), str(user_id)),
            ).fetchone()

        active_days = {datetime.fromtimestamp(int(row["ended_at"]), zone).date() for row in sessions}
        consistency = len(active_days) / 7 * 100
        completed_tasks = sum(1 for row in tasks if row["status"] == "completed")
        plan_completion = completed_tasks / len(tasks) * 100 if tasks else 0.0
        revision_control = max(0.0, 100.0 - min(overdue * 10.0, 100.0))
        subject_minutes: dict[str, int] = defaultdict(int)
        for row in sessions:
            subject_minutes[str(row["subject"]).lower()] += int(row["focus_seconds"]) // 60
        balance = _balance_score(list(subject_minutes.values()))
        factors = {
            "consistency": round(consistency, 2),
            "plan_completion": round(plan_completion, 2),
            "revision_control": round(revision_control, 2),
            "subject_balance": round(balance, 2),
        }
        score = round(consistency * 0.40 + plan_completion * 0.30 + revision_control * 0.20 + balance * 0.10, 2)
        tier = _tier(score)
        points = int(totals["focus_minutes"]) + int(totals["questions"]) // 10 + int(totals["revisions"]) * 5 + int(totals["mocks"]) * 50
        level = max((name for threshold, name in LEVELS if points >= threshold), key=lambda name: next(t for t, n in LEVELS if n == name))
        result = {
            "score": score,
            "tier": tier,
            "factors": factors,
            "level": level,
            "level_points": points,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }
        if persist:
            with self.database.transaction(immediate=True) as conn:
                conn.execute(
                    """
                    INSERT INTO discipline_snapshots(
                        id, user_id, period_start, period_end, score, tier,
                        formula_version, factors_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, period_start, period_end, formula_version) DO UPDATE SET
                        score=excluded.score, tier=excluded.tier,
                        factors_json=excluded.factors_json, created_at=excluded.created_at
                    """,
                    (
                        str(uuid.uuid4()), str(user_id), result["period_start"], result["period_end"],
                        score, tier, FORMULA_VERSION, json.dumps(factors), timestamp,
                    ),
                )
        return result

    def leaderboard(self, *, now: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        timestamp = int(time.time() if now is None else now)
        start = timestamp - 7 * 86400
        with self.database.connect() as conn:
            users = conn.execute(
                """
                SELECT p.user_id, p.display_name, COALESCE(SUM(s.focus_seconds),0) AS focus_seconds
                FROM profiles p LEFT JOIN study_sessions s
                  ON s.user_id=p.user_id AND s.status='completed' AND s.source='live' AND s.ended_at>=?
                WHERE p.leaderboard_visible=1
                GROUP BY p.user_id, p.display_name
                ORDER BY focus_seconds DESC LIMIT ?
                """,
                (start, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in users]


def _balance_score(minutes: list[int]) -> float:
    values = [value for value in minutes if value > 0]
    if not values:
        return 0.0
    if len(values) == 1:
        return 35.0
    total = sum(values)
    entropy = -sum((value / total) * math.log(value / total) for value in values)
    return min(100.0, entropy / math.log(max(3, len(values))) * 100)


def _tier(score: float) -> str:
    if score >= 90:
        return "Elite Discipline"
    if score >= 75:
        return "Highly Disciplined"
    if score >= 60:
        return "Disciplined"
    if score >= 45:
        return "Consistent"
    if score >= 25:
        return "Developing"
    return "Rebuilding"
