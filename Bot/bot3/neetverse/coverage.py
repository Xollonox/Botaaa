"""Personal resource catalog and exact page-range coverage."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .database import Database
from .mastery import MasteryService


class CoverageError(ValueError):
    pass


class CoverageService:
    def __init__(self, database: Database, mastery: MasteryService) -> None:
        self.database = database
        self.mastery = mastery

    def add_resource(
        self,
        user_id: str,
        *,
        name: str,
        resource_type: str,
        subject_code: str | None = None,
        edition: str | None = None,
        total_pages: int | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if not name.strip() or not resource_type.strip():
            raise CoverageError("Resource name and type are required")
        if total_pages is not None and not 1 <= int(total_pages) <= 100_000:
            raise CoverageError("Total pages is invalid")
        timestamp = int(time.time() if now is None else now)
        resource_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone() is None:
                raise CoverageError("Run /start before adding resources")
            conn.execute(
                """
                INSERT INTO resources(
                    id, user_id, name, resource_type, edition, subject_code,
                    total_pages, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource_id, str(user_id), name.strip()[:200], resource_type.strip()[:100],
                    _optional(edition, 100), _optional(subject_code, 100),
                    int(total_pages) if total_pages is not None else None, timestamp, timestamp,
                ),
            )
        return self.get_resource(user_id, resource_id)

    def get_resource(self, user_id: str, resource_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM resources WHERE id=? AND user_id=?", (resource_id, str(user_id))).fetchone()
        if row is None:
            raise CoverageError("Resource not found")
        return dict(row)

    def list_resources(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM resources WHERE user_id=? AND archived=0 ORDER BY name",
                (str(user_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_resource(self, user_id: str, name_or_id: str) -> dict[str, Any]:
        token = name_or_id.strip()
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM resources
                WHERE user_id=? AND archived=0 AND (id=? OR lower(name)=lower(?))
                ORDER BY created_at DESC LIMIT 2
                """,
                (str(user_id), token, token),
            ).fetchall()
        if not rows:
            raise CoverageError("Resource not found")
        if len(rows) > 1:
            raise CoverageError("Multiple resources have that name; use the resource ID")
        return dict(rows[0])

    def record_pages(
        self,
        user_id: str,
        resource_id: str,
        *,
        page_start: int,
        page_end: int,
        activity: str,
        session_id: str | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        start, end = int(page_start), int(page_end)
        if start <= 0 or end < start:
            raise CoverageError("Page range is invalid")
        if not activity.strip():
            raise CoverageError("Coverage activity is required")
        timestamp = int(time.time() if now is None else now)
        coverage_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            resource = conn.execute(
                "SELECT * FROM resources WHERE id=? AND user_id=? AND archived=0",
                (resource_id, str(user_id)),
            ).fetchone()
            if resource is None:
                raise CoverageError("Resource not found")
            if resource["total_pages"] is not None and end > int(resource["total_pages"]):
                raise CoverageError("Page range exceeds the resource’s total pages")
            previous_ranges = conn.execute(
                """
                SELECT page_start, page_end FROM page_coverage
                WHERE user_id=? AND resource_id=? AND lower(activity)=lower(?)
                ORDER BY page_start, page_end
                """,
                (str(user_id), resource_id, activity.strip()),
            ).fetchall()
            previously_covered = _union_size(
                [(int(row["page_start"]), int(row["page_end"])) for row in previous_ranges]
            )
            conn.execute(
                """
                INSERT INTO page_coverage(
                    id, user_id, resource_id, session_id, page_start, page_end, activity, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (coverage_id, str(user_id), resource_id, session_id, start, end, activity.strip()[:100], timestamp),
            )
            ranges = conn.execute(
                """
                SELECT page_start, page_end FROM page_coverage
                WHERE user_id=? AND resource_id=? AND lower(activity)=lower(?)
                ORDER BY page_start, page_end
                """,
                (str(user_id), resource_id, activity.strip()),
            ).fetchall()
            covered_pages = _union_size([(int(row["page_start"]), int(row["page_end"])) for row in ranges])
            new_unique_pages = max(0, covered_pages - previously_covered)
            total_pages = resource["total_pages"]
            percent = min(100.0, covered_pages / int(total_pages) * 100) if total_pages else None
            if percent is not None and resource["subject_code"]:
                evidence_source = f"resource:{resource_id}:{activity.strip().lower()}"
                conn.execute(
                    """
                    INSERT INTO mastery_evidence(
                        id, user_id, subject, evidence_type, score, weight, source_id, occurred_at
                    ) VALUES (?, ?, ?, 'coverage', ?, 0.2, ?, ?)
                    ON CONFLICT(evidence_type, source_id) DO UPDATE SET
                        score=excluded.score, occurred_at=excluded.occurred_at
                    """,
                    (str(uuid.uuid4()), str(user_id), resource["subject_code"], percent, evidence_source, timestamp),
                )
                self.mastery.recalculate(conn, str(user_id), resource["subject_code"], None, now=timestamp)
            self.database.emit_event(
                conn,
                event_type="PageCoverageRecorded",
                aggregate_type="resource",
                aggregate_id=resource_id,
                user_id=str(user_id),
                payload={
                    "activity": activity.strip(), "covered_pages": covered_pages,
                    "new_unique_pages": new_unique_pages, "coverage_percent": percent,
                },
                occurred_at=timestamp,
            )
        return {
            "id": coverage_id,
            "resource_id": resource_id,
            "covered_pages": covered_pages,
            "new_unique_pages": new_unique_pages,
            "total_pages": total_pages,
            "coverage_percent": round(percent, 2) if percent is not None else None,
        }

    def coverage_summary(self, user_id: str, resource_id: str) -> list[dict[str, Any]]:
        resource = self.get_resource(user_id, resource_id)
        with self.database.connect() as conn:
            activities = conn.execute(
                "SELECT DISTINCT activity FROM page_coverage WHERE user_id=? AND resource_id=? ORDER BY activity",
                (str(user_id), resource_id),
            ).fetchall()
            result = []
            for activity_row in activities:
                activity = str(activity_row["activity"])
                ranges = conn.execute(
                    "SELECT page_start, page_end FROM page_coverage WHERE user_id=? AND resource_id=? AND activity=? ORDER BY page_start, page_end",
                    (str(user_id), resource_id, activity),
                ).fetchall()
                covered = _union_size([(int(row["page_start"]), int(row["page_end"])) for row in ranges])
                total = resource["total_pages"]
                result.append({
                    "activity": activity,
                    "covered_pages": covered,
                    "coverage_percent": round(min(100.0, covered / int(total) * 100), 2) if total else None,
                })
        return result


def _union_size(ranges: list[tuple[int, int]]) -> int:
    if not ranges:
        return 0
    total = 0
    current_start, current_end = ranges[0]
    for start, end in ranges[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start + 1
            current_start, current_end = start, end
    return total + current_end - current_start + 1


def _optional(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None
