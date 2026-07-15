"""Persistent reminder queue with claim/retry semantics."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


class ReminderService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def schedule(
        self,
        conn,
        *,
        user_id: str,
        job_type: str,
        due_at: int,
        payload: dict[str, Any],
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        now: int,
    ) -> str:
        if aggregate_type and aggregate_id:
            existing = conn.execute(
                """
                SELECT id FROM reminder_jobs
                WHERE user_id=? AND job_type=? AND aggregate_type=? AND aggregate_id=?
                  AND status IN ('pending','claimed')
                LIMIT 1
                """,
                (str(user_id), job_type, aggregate_type, aggregate_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE reminder_jobs SET payload_json=?, due_at=?, status='pending',
                        attempts=0, claimed_at=NULL, last_error=NULL WHERE id=?
                    """,
                    (json.dumps(payload), int(due_at), existing["id"]),
                )
                return str(existing["id"])
        job_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO reminder_jobs(
                id, user_id, job_type, payload_json, due_at, status,
                aggregate_type, aggregate_id, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (job_id, str(user_id), job_type, json.dumps(payload), int(due_at), aggregate_type, aggregate_id, int(now)),
        )
        return job_id

    def cancel_aggregate(self, conn, user_id: str, aggregate_type: str, aggregate_id: str) -> None:
        conn.execute(
            """
            UPDATE reminder_jobs SET status='cancelled'
            WHERE user_id=? AND aggregate_type=? AND aggregate_id=? AND status IN ('pending','claimed')
            """,
            (str(user_id), aggregate_type, aggregate_id),
        )

    def claim_due(self, *, now: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            # Recover claims abandoned by a process restart.
            conn.execute(
                """
                UPDATE reminder_jobs SET status='pending', claimed_at=NULL
                WHERE status='claimed' AND claimed_at < ?
                """,
                (timestamp - 300,),
            )
            rows = conn.execute(
                """
                SELECT j.* FROM reminder_jobs j
                JOIN profiles p ON p.user_id=j.user_id
                WHERE j.status='pending' AND j.due_at<=? AND p.dm_reminders=1
                ORDER BY j.due_at LIMIT ?
                """,
                (timestamp, max(1, min(int(limit), 100))),
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                job = dict(row)
                profile = conn.execute(
                    "SELECT timezone, quiet_hours_start, quiet_hours_end FROM profiles WHERE user_id=?",
                    (job["user_id"],),
                ).fetchone()
                deferred_until = _quiet_hours_end(timestamp, dict(profile)) if profile else None
                if deferred_until and deferred_until > timestamp:
                    conn.execute("UPDATE reminder_jobs SET due_at=? WHERE id=?", (deferred_until, job["id"]))
                    continue
                conn.execute(
                    "UPDATE reminder_jobs SET status='claimed', claimed_at=?, attempts=attempts+1 WHERE id=?",
                    (timestamp, job["id"]),
                )
                job["payload"] = json.loads(job.pop("payload_json"))
                job["attempts"] = int(job["attempts"]) + 1
                claimed.append(job)
        return claimed

    def delivered(self, job_id: str, *, now: int | None = None) -> None:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE reminder_jobs SET status='delivered', delivered_at=?, claimed_at=NULL WHERE id=? AND status='claimed'",
                (timestamp, job_id),
            )

    def failed(self, job_id: str, error: str, *, now: int | None = None) -> None:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute("SELECT attempts FROM reminder_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"])
            if attempts >= 3:
                conn.execute(
                    "UPDATE reminder_jobs SET status='failed', last_error=?, claimed_at=NULL WHERE id=?",
                    (error[:500], job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE reminder_jobs SET status='pending', due_at=?, last_error=?, claimed_at=NULL
                    WHERE id=?
                    """,
                    (timestamp + attempts * 300, error[:500], job_id),
                )


def _quiet_hours_end(timestamp: int, profile: dict[str, Any]) -> int | None:
    start_text, end_text = profile.get("quiet_hours_start"), profile.get("quiet_hours_end")
    if not start_text or not end_text:
        return None
    try:
        zone = ZoneInfo(profile.get("timezone") or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    local = datetime.fromtimestamp(timestamp, zone)
    start_hour, start_minute = map(int, start_text.split(":"))
    end_hour, end_minute = map(int, end_text.split(":"))
    start = local.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = local.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    if end <= start:
        if local < end:
            start -= timedelta(days=1)
        else:
            end += timedelta(days=1)
    if start <= local < end:
        return int(end.timestamp())
    return None
