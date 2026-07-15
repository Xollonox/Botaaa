"""Privacy-safe student-card metrics composed from canonical services."""

from __future__ import annotations

import time
from typing import Any

from .curriculum import CurriculumError, CurriculumService
from .database import Database
from .discipline import DisciplineService
from .planner import PlannerService
from .streaks import StreakService


class StudentOverviewService:
    def __init__(
        self,
        database: Database,
        curriculum: CurriculumService,
        discipline: DisciplineService,
        planner: PlannerService,
        streaks: StreakService,
    ) -> None:
        self.database = database
        self.curriculum = curriculum
        self.discipline = discipline
        self.planner = planner
        self.streaks = streaks

    def snapshot(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() if now is None else now)
        with self.database.connect() as conn:
            profile = conn.execute(
                """
                SELECT user_id, display_name, onboarding_status, target_year,
                       current_status, current_mock_score, target_score,
                       leaderboard_visible
                FROM profiles WHERE user_id=?
                """,
                (str(user_id),),
            ).fetchone()
            if profile is None:
                raise ValueError("Profile not found")
            totals = conn.execute(
                """
                SELECT
                    COALESCE((SELECT SUM(attempted) FROM practice_batches WHERE user_id=?), 0) questions,
                    COALESCE((SELECT COUNT(*) FROM revision_attempts WHERE user_id=?), 0) revisions,
                    COALESCE((SELECT COUNT(*) FROM mock_attempts WHERE user_id=?), 0) mocks
                """,
                (str(user_id), str(user_id), str(user_id)),
            ).fetchone()

        streak = self.streaks.calculate(user_id, now=timestamp)
        discipline = self.discipline.calculate(user_id, now=timestamp, persist=False)
        plan = self.planner.active_daily_plan(user_id, now=timestamp)
        plan_total = len(plan["tasks"]) if plan else 0
        plan_completed = (
            sum(task["status"] == "completed" for task in plan["tasks"]) if plan else 0
        )
        try:
            syllabus = self.curriculum.summary(user_id)
        except CurriculumError:
            syllabus = None
        syllabus_completion = None
        if syllabus and syllabus["subjects"]:
            leaf_total = sum(int(row["nodes"]) for row in syllabus["subjects"])
            syllabus_completion = (
                sum(float(row["completion"] or 0) * int(row["nodes"]) for row in syllabus["subjects"])
                / leaf_total
                if leaf_total
                else 0.0
            )
        return {
            "profile": dict(profile),
            "streak": streak,
            "discipline": discipline,
            "daily_plan": {
                "title": plan["title"] if plan else None,
                "completed": plan_completed,
                "total": plan_total,
                "completion": plan_completed / plan_total * 100 if plan_total else 0.0,
            },
            "syllabus": syllabus,
            "syllabus_completion": syllabus_completion,
            "totals": {key: int(totals[key]) for key in totals.keys()},
        }
