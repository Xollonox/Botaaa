"""Versioned official syllabus catalog and independent student progress."""

from __future__ import annotations

import time
import uuid
from typing import Any
from urllib.parse import urlparse

from .database import Database


OFFICIAL_SYLLABUS_DOMAINS = {"neet.nta.nic.in", "nta.ac.in", "www.nta.ac.in", "nmc.org.in", "www.nmc.org.in"}
NODE_TYPES = {"subject", "unit", "chapter", "topic", "subtopic"}
PROGRESS_FIELDS = {"lecture_percent", "reading_percent", "notes_percent", "practice_percent", "pyq_percent"}


class CurriculumError(ValueError):
    pass


class CurriculumService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def import_version(self, payload: dict[str, Any], *, activate: bool = False, now: int | None = None) -> str:
        target_year = int(payload.get("target_year") or 0)
        label = str(payload.get("label") or "").strip()
        source_url = str(payload.get("source_url") or "").strip()
        nodes = payload.get("nodes")
        if str(payload.get("exam") or "").strip().upper() != "NEET-UG":
            raise CurriculumError("Syllabus exam must be NEET-UG")
        if not 2025 <= target_year <= 2100 or not label:
            raise CurriculumError("A valid target year and label are required")
        if (urlparse(source_url).hostname or "").lower() not in OFFICIAL_SYLLABUS_DOMAINS:
            raise CurriculumError("Syllabus source must be an official NTA or NMC URL")
        if not isinstance(nodes, list) or not nodes:
            raise CurriculumError("Syllabus nodes are required")

        normalized: list[dict[str, Any]] = []
        keys: set[str] = set()
        for index, raw in enumerate(nodes):
            if not isinstance(raw, dict):
                raise CurriculumError("Every syllabus node must be an object")
            key = str(raw.get("key") or "").strip()
            node_type = str(raw.get("node_type") or "").strip().lower()
            subject = str(raw.get("subject_code") or "").strip().lower()
            name = str(raw.get("name") or "").strip()
            parent_key = str(raw.get("parent_key") or "").strip() or None
            if not key or key in keys or node_type not in NODE_TYPES or not subject or not name:
                raise CurriculumError(f"Invalid or duplicate syllabus node at position {index + 1}")
            keys.add(key)
            normalized.append({
                "key": key, "parent_key": parent_key, "node_type": node_type,
                "subject_code": subject[:40], "name": name[:300],
                "sort_order": int(raw.get("sort_order") or index),
            })
        if any(node["parent_key"] and node["parent_key"] not in keys for node in normalized):
            raise CurriculumError("A syllabus node refers to a missing parent_key")

        timestamp = int(time.time() if now is None else now)
        version_id = str(uuid.uuid4())
        node_ids = {node["key"]: str(uuid.uuid4()) for node in normalized}
        with self.database.transaction(immediate=True) as conn:
            if activate:
                conn.execute(
                    "UPDATE curriculum_versions SET status='retired' WHERE exam='NEET-UG' AND target_year=? AND status='active'",
                    (target_year,),
                )
            conn.execute(
                """
                INSERT INTO curriculum_versions
                (id, exam, target_year, label, source_url, source_published_at, status, created_at)
                VALUES (?, 'NEET-UG', ?, ?, ?, ?, ?, ?)
                """,
                (version_id, target_year, label[:200], source_url,
                 _optional_int(payload.get("source_published_at")), "active" if activate else "draft", timestamp),
            )
            remaining = list(normalized)
            inserted: set[str] = set()
            while remaining:
                progressed = False
                for node in remaining[:]:
                    if node["parent_key"] and node["parent_key"] not in inserted:
                        continue
                    conn.execute(
                        """
                        INSERT INTO curriculum_nodes
                        (id, version_id, parent_id, node_type, subject_code, name, sort_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (node_ids[node["key"]], version_id,
                         node_ids.get(node["parent_key"]), node["node_type"],
                         node["subject_code"], node["name"], node["sort_order"]),
                    )
                    inserted.add(node["key"])
                    remaining.remove(node)
                    progressed = True
                if not progressed:
                    raise CurriculumError("Syllabus parent relationships contain a cycle")
        return version_id

    def active_for_user(self, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT cv.* FROM profiles p
                JOIN curriculum_versions cv ON cv.target_year=p.target_year
                WHERE p.user_id=? AND cv.exam='NEET-UG' AND cv.status='active'
                ORDER BY cv.created_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
        return dict(row) if row else None

    def find_nodes(self, user_id: str, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        version = self.active_for_user(user_id)
        if version is None:
            raise CurriculumError("No active official syllabus is loaded for your target year")
        pattern = f"%{query.strip()}%"
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT n.*, cp.lecture_percent, cp.reading_percent, cp.notes_percent,
                       cp.practice_percent, cp.pyq_percent, cp.revision_count
                FROM curriculum_nodes n
                LEFT JOIN curriculum_progress cp ON cp.node_id=n.id AND cp.user_id=?
                WHERE n.version_id=? AND (n.name LIKE ? OR n.id LIKE ?)
                ORDER BY n.sort_order, n.name LIMIT ?
                """,
                (str(user_id), version["id"], pattern, pattern, max(1, min(50, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_progress(self, user_id: str, node_id: str, field: str, percent: float, *, now: int | None = None) -> dict[str, Any]:
        if field not in PROGRESS_FIELDS or not 0 <= float(percent) <= 100:
            raise CurriculumError("Choose a valid progress type and percentage from 0 to 100")
        version = self.active_for_user(user_id)
        if version is None:
            raise CurriculumError("No active official syllabus is loaded for your target year")
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            node = conn.execute(
                "SELECT * FROM curriculum_nodes WHERE id=? AND version_id=?", (node_id, version["id"])
            ).fetchone()
            if node is None:
                raise CurriculumError("That syllabus node does not belong to your target-year syllabus")
            conn.execute(
                """
                INSERT INTO curriculum_progress(user_id, node_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, node_id) DO NOTHING
                """,
                (str(user_id), node_id, timestamp),
            )
            conn.execute(
                f"UPDATE curriculum_progress SET {field}=?, updated_at=? WHERE user_id=? AND node_id=?",
                (float(percent), timestamp, str(user_id), node_id),
            )
            row = conn.execute(
                "SELECT * FROM curriculum_progress WHERE user_id=? AND node_id=?", (str(user_id), node_id)
            ).fetchone()
            self.database.emit_event(
                conn, event_type="SyllabusProgressUpdated", aggregate_type="curriculum_node",
                aggregate_id=node_id, user_id=str(user_id),
                payload={"field": field, "percent": float(percent)}, occurred_at=timestamp,
            )
        result = dict(row)
        result["node_name"] = node["name"]
        return result

    def summary(self, user_id: str) -> dict[str, Any]:
        version = self.active_for_user(user_id)
        if version is None:
            raise CurriculumError("No active official syllabus is loaded for your target year")
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT n.subject_code, COUNT(*) AS nodes,
                    AVG((COALESCE(cp.lecture_percent,0)+COALESCE(cp.reading_percent,0)+
                         COALESCE(cp.notes_percent,0)+COALESCE(cp.practice_percent,0)+
                         COALESCE(cp.pyq_percent,0))/5.0) AS completion
                FROM curriculum_nodes n
                LEFT JOIN curriculum_progress cp ON cp.node_id=n.id AND cp.user_id=?
                WHERE n.version_id=? AND n.node_type IN ('chapter','topic','subtopic')
                GROUP BY n.subject_code ORDER BY n.subject_code
                """,
                (str(user_id), version["id"]),
            ).fetchall()
        return {"version": version, "subjects": [dict(row) for row in rows]}


def _optional_int(value: Any) -> int | None:
    return int(value) if value not in (None, "") else None
