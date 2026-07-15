"""Time-zone-aware streaks derived only from verified live study sessions."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


class StreakService:
    """Calculate transparent streaks without storing a second source of truth."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def calculate(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            profile = conn.execute(
                "SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)
            ).fetchone()
            if profile is None:
                raise ValueError("Run /start first")
            if not profile["timezone"]:
                raise ValueError("Set your time zone in /start before tracking a streak")
            try:
                zone = ZoneInfo(str(profile["timezone"]))
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Your profile time zone is invalid") from exc
            sessions = conn.execute(
                """
                SELECT ended_at, focus_seconds FROM study_sessions
                WHERE user_id=? AND status='completed' AND source='live'
                  AND focus_seconds>0 AND ended_at IS NOT NULL AND ended_at<=?
                ORDER BY ended_at
                """,
                (str(user_id), timestamp),
            ).fetchall()

        by_day: dict[date, int] = {}
        for row in sessions:
            local_day = datetime.fromtimestamp(int(row["ended_at"]), zone).date()
            by_day[local_day] = by_day.get(local_day, 0) + int(row["focus_seconds"])

        today = datetime.fromtimestamp(timestamp, zone).date()
        anchor = today if by_day.get(today, 0) > 0 else today - timedelta(days=1)
        current = 0
        cursor = anchor
        while by_day.get(cursor, 0) > 0:
            current += 1
            cursor -= timedelta(days=1)

        longest = 0
        run = 0
        previous: date | None = None
        for active_day in sorted(by_day):
            run = run + 1 if previous is not None and active_day == previous + timedelta(days=1) else 1
            longest = max(longest, run)
            previous = active_day

        recent_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        recent = [
            {
                "date": day.isoformat(),
                "weekday": day.strftime("%a")[0],
                "active": by_day.get(day, 0) > 0,
                "focus_seconds": by_day.get(day, 0),
            }
            for day in recent_days
        ]
        return {
            "current": current,
            "longest": longest,
            "today_seconds": by_day.get(today, 0),
            "week_seconds": sum(item["focus_seconds"] for item in recent),
            "active_days_week": sum(item["active"] for item in recent),
            "total_verified_seconds": sum(by_day.values()),
            "calendar": recent,
            "timezone": str(zone),
            "rule": "A day counts after at least one completed live-timed focus session.",
        }
