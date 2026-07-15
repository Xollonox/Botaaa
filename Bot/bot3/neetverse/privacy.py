"""Student data export and complete account deletion."""

from __future__ import annotations

import time
from typing import Any

from .database import Database


EXPORT_TABLES = (
    "profiles", "profile_subject_progress", "profile_change_log", "study_sessions",
    "plans", "tasks", "ai_usage", "ai_proposals", "curriculum_progress",
    "resources", "page_coverage", "practice_batches", "mistakes", "revision_items",
    "revision_attempts", "mastery_evidence", "mastery_snapshots", "mock_attempts",
    "reminder_jobs", "discipline_snapshots", "saved_lectures", "goals", "domain_events",
)


class PrivacyService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def export(self, user_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            exists = conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if exists is None:
                raise ValueError("No NeetVerse profile exists for this account")
            data: dict[str, list[dict[str, Any]]] = {}
            for table in EXPORT_TABLES:
                rows = conn.execute(f"SELECT * FROM {table} WHERE user_id=?", (str(user_id),)).fetchall()
                if rows:
                    data[table] = [dict(row) for row in rows]
            mock_ids = [row["id"] for row in data.get("mock_attempts", [])]
            data["mock_sections"] = []
            for mock_id in mock_ids:
                data["mock_sections"].extend(
                    dict(row) for row in conn.execute("SELECT * FROM mock_sections WHERE mock_id=?", (mock_id,)).fetchall()
                )
        return {"exported_at": int(time.time()), "user_id": str(user_id), "data": data}

    def delete(self, user_id: str) -> bool:
        with self.database.transaction(immediate=True) as conn:
            exists = conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone()
            if exists is None:
                return False
            # These three audit/usage tables deliberately have no profile FK.
            conn.execute("DELETE FROM ai_usage WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM domain_events WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM interaction_receipts WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM profiles WHERE user_id=?", (str(user_id),))
        return True
