"""User-approved plan proposals and task persistence."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .database import Database


class PlannerError(ValueError):
    pass


class PlannerService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def approve_ai_proposal(self, user_id: str, proposal_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            proposal = conn.execute(
                "SELECT * FROM ai_proposals WHERE id=? AND user_id=?",
                (proposal_id, str(user_id)),
            ).fetchone()
            if proposal is None or proposal["status"] != "pending":
                raise PlannerError("This plan proposal is no longer available")
            profile = conn.execute("SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None or not profile["timezone"]:
                raise PlannerError("Set your time zone before approving a daily plan")
            try:
                local_date = datetime.fromtimestamp(timestamp, ZoneInfo(profile["timezone"])).date().isoformat()
            except ZoneInfoNotFoundError as exc:
                raise PlannerError("Your profile time zone is invalid") from exc
            payload = json.loads(proposal["payload_json"])
            tasks = payload.get("tasks", [])
            if not isinstance(tasks, list) or not tasks:
                raise PlannerError("This proposal has no valid tasks")
            plan_id = str(uuid.uuid4())
            conn.execute(
                """
                UPDATE plans SET status='archived', updated_at=?
                WHERE user_id=? AND period_type='daily' AND status='active' AND starts_on=?
                """,
                (timestamp, str(user_id), local_date),
            )
            conn.execute(
                """
                INSERT INTO plans(id, user_id, title, period_type, status, starts_on, ends_on, source, created_at, updated_at)
                VALUES (?, ?, ?, 'daily', 'active', ?, ?, 'ai_approved', ?, ?)
                """,
                (
                    plan_id, str(user_id), str(payload.get("title", "Daily NEET Plan"))[:200],
                    local_date, local_date, timestamp, timestamp,
                ),
            )
            for task in tasks:
                if not isinstance(task, dict) or not task.get("title"):
                    continue
                conn.execute(
                    """
                    INSERT INTO tasks(
                        id, plan_id, user_id, title, subject, chapter, activity,
                        estimated_minutes, priority, status, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'ai_approved', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), plan_id, str(user_id), str(task["title"])[:200],
                        _optional(task.get("subject"), 100), _optional(task.get("chapter"), 150),
                        _optional(task.get("activity"), 100), int(task.get("estimated_minutes", 30)),
                        int(task.get("priority", 3)), timestamp, timestamp,
                    ),
                )
            conn.execute(
                "UPDATE ai_proposals SET status='approved', resolved_at=? WHERE id=?",
                (timestamp, proposal_id),
            )
            self.database.emit_event(
                conn,
                event_type="PlanApproved",
                aggregate_type="plan",
                aggregate_id=plan_id,
                user_id=str(user_id),
                payload={"proposal_id": proposal_id, "source": "ai_approved"},
                occurred_at=timestamp,
            )
        return self.get_plan(plan_id, user_id)

    def create_manual_plan(
        self,
        user_id: str,
        *,
        title: str,
        period_type: str,
        starts_on: str,
        ends_on: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        if period_type not in {"daily", "weekly", "monthly", "roadmap", "custom"}:
            raise PlannerError("Invalid plan period")
        title = title.strip()
        if not title:
            raise PlannerError("Plan title is required")
        try:
            start = datetime.fromisoformat(starts_on).date()
            end = datetime.fromisoformat(ends_on).date()
        except ValueError as exc:
            raise PlannerError("Plan dates must use YYYY-MM-DD") from exc
        if end < start:
            raise PlannerError("Plan end date cannot be before its start")
        timestamp = int(time.time() if now is None else now)
        plan_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            profile = conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None:
                raise PlannerError("Run /start before creating a plan")
            if period_type == "daily":
                conn.execute(
                    """
                    UPDATE plans SET status='archived', updated_at=?
                    WHERE user_id=? AND period_type='daily' AND status='active' AND starts_on=?
                    """,
                    (timestamp, str(user_id), start.isoformat()),
                )
            conn.execute(
                """
                INSERT INTO plans(id, user_id, title, period_type, status, starts_on, ends_on, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, 'manual', ?, ?)
                """,
                (plan_id, str(user_id), title[:200], period_type, start.isoformat(), end.isoformat(), timestamp, timestamp),
            )
            self.database.emit_event(
                conn, event_type="PlanCreated", aggregate_type="plan", aggregate_id=plan_id,
                user_id=str(user_id), payload={"source": "manual", "period_type": period_type}, occurred_at=timestamp,
            )
        return self.get_plan(plan_id, user_id)

    def add_task(
        self,
        user_id: str,
        plan_token: str,
        *,
        title: str,
        subject: str | None = None,
        chapter: str | None = None,
        activity: str | None = None,
        estimated_minutes: int | None = None,
        priority: int = 3,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise PlannerError("Task title is required")
        if estimated_minutes is not None and not 1 <= int(estimated_minutes) <= 1440:
            raise PlannerError("Estimated time must be between 1 and 1440 minutes")
        if not 1 <= int(priority) <= 5:
            raise PlannerError("Priority must be between 1 and 5")
        timestamp = int(time.time() if now is None else now)
        task_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            plans = conn.execute(
                "SELECT * FROM plans WHERE user_id=? AND id LIKE ? AND status IN ('draft','active') LIMIT 2",
                (str(user_id), f"{plan_token.strip()}%"),
            ).fetchall()
            if not plans:
                raise PlannerError("Active plan not found")
            if len(plans) > 1:
                raise PlannerError("Plan ID is ambiguous; provide more characters")
            plan = plans[0]
            conn.execute(
                """
                INSERT INTO tasks(id, plan_id, user_id, title, subject, chapter, activity,
                    estimated_minutes, priority, status, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'manual', ?, ?)
                """,
                (task_id, plan["id"], str(user_id), title.strip()[:200], _optional(subject, 100),
                 _optional(chapter, 150), _optional(activity, 100), estimated_minutes,
                 int(priority), timestamp, timestamp),
            )
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(task)

    def list_plans(self, user_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*, COUNT(t.id) AS task_count,
                       SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END) AS completed_count
                FROM plans p LEFT JOIN tasks t ON t.plan_id=p.id
                WHERE p.user_id=? GROUP BY p.id ORDER BY p.created_at DESC LIMIT ?
                """,
                (str(user_id), max(1, min(25, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def reject_ai_proposal(self, user_id: str, proposal_id: str, *, now: int | None = None) -> bool:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            cur = conn.execute(
                """
                UPDATE ai_proposals SET status='rejected', resolved_at=?
                WHERE id=? AND user_id=? AND status='pending'
                """,
                (timestamp, proposal_id, str(user_id)),
            )
            return cur.rowcount > 0

    def get_plan(self, plan_id: str, user_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE id=? AND user_id=?", (plan_id, str(user_id))).fetchone()
            if plan is None:
                raise PlannerError("Plan not found")
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE plan_id=? AND user_id=? ORDER BY priority, created_at",
                (plan_id, str(user_id)),
            ).fetchall()
        out = dict(plan)
        out["tasks"] = [dict(task) for task in tasks]
        return out

    def active_daily_plan(self, user_id: str, *, now: int | None = None) -> dict[str, Any] | None:
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            profile = conn.execute("SELECT timezone FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if profile is None or not profile["timezone"]:
                return None
            try:
                local_date = datetime.fromtimestamp(timestamp, ZoneInfo(profile["timezone"])).date().isoformat()
            except ZoneInfoNotFoundError:
                return None
            row = conn.execute(
                """
                SELECT id FROM plans WHERE user_id=? AND period_type='daily' AND status='active'
                  AND starts_on<=? AND ends_on>=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (str(user_id), local_date, local_date),
            ).fetchone()
        return self.get_plan(row["id"], user_id) if row else None

    def complete_task(self, user_id: str, task_token: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks WHERE user_id=? AND id LIKE ? AND status IN ('pending','in_progress')
                ORDER BY created_at DESC LIMIT 2
                """,
                (str(user_id), f"{task_token.strip()}%"),
            ).fetchall()
            if not rows:
                raise PlannerError("Pending task not found")
            if len(rows) > 1:
                raise PlannerError("Task ID is ambiguous; provide more characters")
            task = rows[0]
            conn.execute("UPDATE tasks SET status='completed', updated_at=? WHERE id=?", (timestamp, task["id"]))
            self.database.emit_event(
                conn,
                event_type="TaskCompleted",
                aggregate_type="task",
                aggregate_id=task["id"],
                user_id=str(user_id),
                payload={"plan_id": task["plan_id"], "subject": task["subject"]},
                occurred_at=timestamp,
            )
        return {**dict(task), "status": "completed", "updated_at": timestamp}


def _optional(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
