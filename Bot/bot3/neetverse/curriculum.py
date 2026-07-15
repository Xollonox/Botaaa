"""Versioned official syllabus catalog and independent student progress."""

from __future__ import annotations

import time
import uuid
import json
from pathlib import Path
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

    def ensure_bundled_version(self, payload: dict[str, Any], *, now: int | None = None) -> str:
        """Install reviewed bundled data once without replacing a later owner import."""

        label = str(payload.get("label") or "").strip()
        source_url = str(payload.get("source_url") or "").strip()
        target_year = int(payload.get("target_year") or 0)
        with self.database.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, status FROM curriculum_versions
                WHERE exam='NEET-UG' AND target_year=? AND label=? AND source_url=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (target_year, label, source_url),
            ).fetchone()
            has_active = conn.execute(
                """
                SELECT 1 FROM curriculum_versions
                WHERE exam='NEET-UG' AND target_year=? AND status='active' LIMIT 1
                """,
                (target_year,),
            ).fetchone()
        if existing:
            if has_active is None and existing["status"] != "active":
                with self.database.transaction(immediate=True) as conn:
                    conn.execute(
                        "UPDATE curriculum_versions SET status='active' WHERE id=?",
                        (existing["id"],),
                    )
            return str(existing["id"])
        return self.import_version(payload, activate=has_active is None, now=now)

    def active_for_user(self, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            selected = conn.execute(
                """
                SELECT cv.* FROM profile_curriculum_selections pcs
                JOIN curriculum_versions cv ON cv.id=pcs.version_id
                WHERE pcs.user_id=? AND cv.exam='NEET-UG' AND cv.status='active'
                LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            if selected:
                return dict(selected)
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

    def list_versions(self) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT cv.*, COUNT(cn.id) AS node_count
                FROM curriculum_versions cv
                LEFT JOIN curriculum_nodes cn ON cn.version_id=cv.id
                WHERE cv.exam='NEET-UG' AND cv.status='active'
                GROUP BY cv.id ORDER BY cv.target_year DESC, cv.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def select_version(self, user_id: str, version_token: str, *, now: int | None = None) -> dict[str, Any]:
        token = version_token.strip()
        if not token:
            raise CurriculumError("Choose a syllabus version ID")
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            profile = conn.execute(
                "SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)
            ).fetchone()
            if profile is None:
                raise CurriculumError("Run /start first")
            rows = conn.execute(
                """
                SELECT * FROM curriculum_versions
                WHERE exam='NEET-UG' AND status='active' AND id LIKE ?
                ORDER BY created_at DESC LIMIT 2
                """,
                (f"{token}%",),
            ).fetchall()
            if not rows:
                raise CurriculumError("Active syllabus version not found")
            if len(rows) > 1:
                raise CurriculumError("Syllabus version ID is ambiguous; provide more characters")
            version = rows[0]
            conn.execute(
                """
                INSERT INTO profile_curriculum_selections(user_id, version_id, selected_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    version_id=excluded.version_id, selected_at=excluded.selected_at
                """,
                (str(user_id), version["id"], timestamp),
            )
            self.database.emit_event(
                conn,
                event_type="CurriculumVersionSelected",
                aggregate_type="curriculum_version",
                aggregate_id=str(version["id"]),
                user_id=str(user_id),
                payload={"target_year": int(version["target_year"])},
                occurred_at=timestamp,
            )
        return dict(version)

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

    def browse_nodes(
        self,
        user_id: str,
        *,
        subject: str | None = None,
        parent_token: str | None = None,
    ) -> dict[str, Any]:
        version = self.active_for_user(user_id)
        if version is None:
            raise CurriculumError("No syllabus is selected. Use /syllabus versions, then /syllabus use")
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT n.*, cp.lecture_percent, cp.reading_percent, cp.notes_percent,
                       cp.practice_percent, cp.pyq_percent, cp.revision_count
                FROM curriculum_nodes n
                LEFT JOIN curriculum_progress cp ON cp.node_id=n.id AND cp.user_id=?
                WHERE n.version_id=? ORDER BY n.sort_order, n.name
                """,
                (str(user_id), version["id"]),
            ).fetchall()
        nodes = [dict(row) for row in rows]
        by_id = {row["id"]: row for row in nodes}
        children: dict[str | None, list[dict[str, Any]]] = {}
        for row in nodes:
            children.setdefault(row["parent_id"], []).append(row)

        parent: dict[str, Any] | None = None
        if parent_token:
            matches = [row for row in nodes if str(row["id"]).startswith(parent_token.strip())]
            if not matches:
                raise CurriculumError("No syllabus parent matches that ID")
            if len(matches) > 1:
                raise CurriculumError("Syllabus parent ID is ambiguous; provide more characters")
            parent = matches[0]
        elif subject:
            code = subject.strip().lower()
            parent = next(
                (row for row in nodes if row["node_type"] == "subject" and row["subject_code"].lower() == code),
                None,
            )
            if parent is None:
                raise CurriculumError("That subject is not present in the selected syllabus")

        def leaf_completions(node_id: str) -> list[float]:
            direct = children.get(node_id, [])
            if not direct:
                row = by_id[node_id]
                return [_node_completion(row)]
            values: list[float] = []
            for child in direct:
                values.extend(leaf_completions(child["id"]))
            return values

        visible = children.get(parent["id"] if parent else None, [])
        decorated: list[dict[str, Any]] = []
        for row in visible:
            values = leaf_completions(row["id"])
            decorated.append({
                **row,
                "completion": sum(values) / len(values) if values else 0.0,
                "leaf_count": len(values),
                "has_children": bool(children.get(row["id"])),
            })
        return {"version": version, "parent": parent, "nodes": decorated}

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
            descendants = conn.execute(
                """
                WITH RECURSIVE tree(id) AS (
                    SELECT id FROM curriculum_nodes WHERE id=?
                    UNION ALL
                    SELECT child.id FROM curriculum_nodes child JOIN tree ON child.parent_id=tree.id
                )
                SELECT tree.id FROM tree
                WHERE NOT EXISTS (SELECT 1 FROM curriculum_nodes child WHERE child.parent_id=tree.id)
                """,
                (node_id,),
            ).fetchall()
            leaf_ids = [str(row["id"]) for row in descendants]
            conn.executemany(
                """
                INSERT INTO curriculum_progress(user_id, node_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, node_id) DO NOTHING
                """,
                [(str(user_id), leaf_id, timestamp) for leaf_id in leaf_ids],
            )
            conn.executemany(
                f"UPDATE curriculum_progress SET {field}=?, updated_at=? WHERE user_id=? AND node_id=?",
                [(float(percent), timestamp, str(user_id), leaf_id) for leaf_id in leaf_ids],
            )
            progress_rows = conn.execute(
                f"""
                SELECT AVG(lecture_percent) lecture_percent,
                       AVG(reading_percent) reading_percent,
                       AVG(notes_percent) notes_percent,
                       AVG(practice_percent) practice_percent,
                       AVG(pyq_percent) pyq_percent,
                       CAST(AVG(revision_count) AS INTEGER) revision_count,
                       MAX(updated_at) updated_at
                FROM curriculum_progress
                WHERE user_id=? AND node_id IN ({','.join('?' for _ in leaf_ids)})
                """,
                (str(user_id), *leaf_ids),
            ).fetchone()
            self.database.emit_event(
                conn, event_type="SyllabusProgressUpdated", aggregate_type="curriculum_node",
                aggregate_id=node_id, user_id=str(user_id),
                payload={"field": field, "percent": float(percent), "affected_nodes": len(leaf_ids)}, occurred_at=timestamp,
            )
        result = dict(progress_rows)
        result["node_name"] = node["name"]
        result["affected_nodes"] = len(leaf_ids)
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
                WHERE n.version_id=?
                  AND NOT EXISTS (SELECT 1 FROM curriculum_nodes child WHERE child.parent_id=n.id)
                GROUP BY n.subject_code ORDER BY n.subject_code
                """,
                (str(user_id), version["id"]),
            ).fetchall()
        return {"version": version, "subjects": [dict(row) for row in rows]}


def _optional_int(value: Any) -> int | None:
    return int(value) if value not in (None, "") else None


def _node_completion(row: dict[str, Any]) -> float:
    return sum(float(row.get(field) or 0) for field in PROGRESS_FIELDS) / len(PROGRESS_FIELDS)


def load_bundled_syllabus(path: str | Path) -> dict[str, Any]:
    """Expand a compact reviewed subject/unit/topic/subtopic catalog for import."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes: list[dict[str, Any]] = []
    for subject_index, subject in enumerate(raw.pop("subjects")):
        code = str(subject["code"]).strip().lower()
        subject_key = f"s{subject_index}-{code}"
        nodes.append({
            "key": subject_key,
            "node_type": "subject",
            "subject_code": code,
            "name": subject["name"],
            "sort_order": subject_index,
        })
        for unit_index, unit in enumerate(subject["units"]):
            unit_key = f"{subject_key}-u{unit_index}"
            nodes.append({
                "key": unit_key,
                "parent_key": subject_key,
                "node_type": "unit",
                "subject_code": code,
                "name": unit["name"],
                "sort_order": unit_index,
            })
            for topic_index, topic in enumerate(unit["topics"]):
                topic_key = f"{unit_key}-t{topic_index}"
                nodes.append({
                    "key": topic_key,
                    "parent_key": unit_key,
                    "node_type": "topic",
                    "subject_code": code,
                    "name": topic["name"],
                    "sort_order": topic_index,
                })
                for subtopic_index, subtopic in enumerate(topic["subtopics"]):
                    nodes.append({
                        "key": f"{topic_key}-s{subtopic_index}",
                        "parent_key": topic_key,
                        "node_type": "subtopic",
                        "subject_code": code,
                        "name": subtopic,
                        "sort_order": subtopic_index,
                    })
    raw["nodes"] = nodes
    return raw
