"""SQLite source of truth and schema migrations for NeetVerse."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


LATEST_SCHEMA_VERSION = 7


class _ClosingConnection(sqlite3.Connection):
    """Preserve sqlite transaction semantics and close after a with block."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._migration_lock = threading.Lock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path, timeout=10, isolation_level=None, factory=_ClosingConnection
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        with self._migration_lock, self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
            )
            current = int(conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])
            if current < 1:
                self._apply_v1(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, int(time.time())),
                )
            if current < 2:
                self._apply_v2(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, int(time.time())),
                )
            if current < 3:
                self._apply_v3(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, int(time.time())),
                )
            if current < 4:
                self._apply_v4(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (4, int(time.time())),
                )
            if current < 5:
                self._apply_v5(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (5, int(time.time())),
                )
            if current < 6:
                self._apply_v6(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (6, int(time.time())),
                )
            if current < 7:
                self._apply_v7(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (7, int(time.time())),
                )
            if current > LATEST_SCHEMA_VERSION:
                raise RuntimeError(f"Database schema {current} is newer than this bot supports")

    @staticmethod
    def _apply_v1(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE profiles (
                user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                onboarding_status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (onboarding_status IN ('draft', 'complete')),
                target_year INTEGER,
                current_status TEXT,
                coaching TEXT,
                timezone TEXT,
                weekday_available_minutes INTEGER CHECK (weekday_available_minutes IS NULL OR weekday_available_minutes >= 0),
                weekend_available_minutes INTEGER CHECK (weekend_available_minutes IS NULL OR weekend_available_minutes >= 0),
                current_mock_score REAL CHECK (current_mock_score IS NULL OR current_mock_score BETWEEN 0 AND 720),
                target_score REAL CHECK (target_score IS NULL OR target_score BETWEEN 0 AND 720),
                preferred_language TEXT,
                pomodoro_focus_minutes INTEGER CHECK (pomodoro_focus_minutes IS NULL OR pomodoro_focus_minutes BETWEEN 1 AND 240),
                pomodoro_short_break_minutes INTEGER CHECK (pomodoro_short_break_minutes IS NULL OR pomodoro_short_break_minutes BETWEEN 1 AND 120),
                pomodoro_long_break_minutes INTEGER CHECK (pomodoro_long_break_minutes IS NULL OR pomodoro_long_break_minutes BETWEEN 1 AND 180),
                pomodoro_cycles INTEGER CHECK (pomodoro_cycles IS NULL OR pomodoro_cycles BETWEEN 1 AND 20),
                resources_json TEXT NOT NULL DEFAULT '[]',
                preparation_problems_json TEXT NOT NULL DEFAULT '[]',
                leaderboard_visible INTEGER NOT NULL DEFAULT 0 CHECK (leaderboard_visible IN (0, 1)),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE profile_subject_progress (
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                subject_code TEXT NOT NULL,
                progress_note TEXT,
                progress_percent REAL CHECK (progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100),
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, subject_code)
            );

            CREATE TABLE profile_change_log (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                field_name TEXT NOT NULL,
                old_value_json TEXT,
                new_value_json TEXT,
                source TEXT NOT NULL,
                changed_at INTEGER NOT NULL
            );

            CREATE TABLE study_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                mode TEXT NOT NULL CHECK (mode IN ('stopwatch', 'countdown', 'pomodoro', 'manual')),
                status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'on_break', 'completed', 'cancelled', 'abandoned', 'review_required')),
                phase TEXT NOT NULL DEFAULT 'focus' CHECK (phase IN ('focus', 'short_break', 'long_break')),
                resume_phase TEXT CHECK (resume_phase IS NULL OR resume_phase IN ('focus', 'short_break', 'long_break')),
                phase_elapsed_seconds INTEGER NOT NULL DEFAULT 0 CHECK (phase_elapsed_seconds >= 0),
                subject TEXT NOT NULL,
                chapter TEXT,
                topic TEXT,
                activity TEXT NOT NULL,
                planned_seconds INTEGER CHECK (planned_seconds IS NULL OR planned_seconds > 0),
                focus_seconds INTEGER NOT NULL DEFAULT 0 CHECK (focus_seconds >= 0),
                paused_seconds INTEGER NOT NULL DEFAULT 0 CHECK (paused_seconds >= 0),
                break_seconds INTEGER NOT NULL DEFAULT 0 CHECK (break_seconds >= 0),
                state_started_at INTEGER NOT NULL,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                pomodoro_focus_minutes INTEGER,
                pomodoro_short_break_minutes INTEGER,
                pomodoro_long_break_minutes INTEGER,
                pomodoro_cycles_target INTEGER,
                pomodoro_cycles_completed INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                source TEXT NOT NULL DEFAULT 'live',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE UNIQUE INDEX one_active_session_per_user
            ON study_sessions(user_id)
            WHERE status IN ('running', 'paused', 'on_break');

            CREATE TABLE plans (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                period_type TEXT NOT NULL CHECK (period_type IN ('daily', 'weekly', 'monthly', 'roadmap', 'custom')),
                status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'completed', 'archived')),
                starts_on TEXT,
                ends_on TEXT,
                source TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                plan_id TEXT REFERENCES plans(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                subject TEXT,
                chapter TEXT,
                activity TEXT,
                estimated_minutes INTEGER CHECK (estimated_minutes IS NULL OR estimated_minutes > 0),
                priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
                due_at INTEGER,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped', 'rescheduled')),
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE domain_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                user_id TEXT,
                payload_json TEXT NOT NULL,
                occurred_at INTEGER NOT NULL,
                processed_at INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );

            CREATE INDEX pending_domain_events ON domain_events(processed_at, occurred_at);

            CREATE TABLE ai_usage (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                model_requested TEXT NOT NULL,
                model_used TEXT,
                request_id TEXT,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error_code TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX ai_usage_by_day ON ai_usage(created_at, user_id);

            CREATE TABLE ai_proposals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                proposal_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
                model_used TEXT,
                created_at INTEGER NOT NULL,
                resolved_at INTEGER
            );

            CREATE TABLE interaction_receipts (
                interaction_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            """
        )

    @staticmethod
    def _apply_v2(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE curriculum_versions (
                id TEXT PRIMARY KEY,
                exam TEXT NOT NULL,
                target_year INTEGER NOT NULL,
                label TEXT NOT NULL,
                source_url TEXT,
                source_published_at INTEGER,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
                created_at INTEGER NOT NULL
            );

            CREATE TABLE curriculum_nodes (
                id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL REFERENCES curriculum_versions(id) ON DELETE CASCADE,
                parent_id TEXT REFERENCES curriculum_nodes(id) ON DELETE CASCADE,
                node_type TEXT NOT NULL CHECK (node_type IN ('subject', 'unit', 'chapter', 'topic', 'subtopic')),
                subject_code TEXT NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(version_id, parent_id, name)
            );

            CREATE TABLE curriculum_progress (
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                node_id TEXT NOT NULL REFERENCES curriculum_nodes(id) ON DELETE CASCADE,
                lecture_percent REAL NOT NULL DEFAULT 0 CHECK (lecture_percent BETWEEN 0 AND 100),
                reading_percent REAL NOT NULL DEFAULT 0 CHECK (reading_percent BETWEEN 0 AND 100),
                notes_percent REAL NOT NULL DEFAULT 0 CHECK (notes_percent BETWEEN 0 AND 100),
                practice_percent REAL NOT NULL DEFAULT 0 CHECK (practice_percent BETWEEN 0 AND 100),
                pyq_percent REAL NOT NULL DEFAULT 0 CHECK (pyq_percent BETWEEN 0 AND 100),
                revision_count INTEGER NOT NULL DEFAULT 0 CHECK (revision_count >= 0),
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(user_id, node_id)
            );

            CREATE TABLE resources (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                edition TEXT,
                subject_code TEXT,
                total_pages INTEGER CHECK (total_pages IS NULL OR total_pages > 0),
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE page_coverage (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
                curriculum_node_id TEXT REFERENCES curriculum_nodes(id) ON DELETE SET NULL,
                session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
                page_start INTEGER NOT NULL CHECK (page_start > 0),
                page_end INTEGER NOT NULL CHECK (page_end >= page_start),
                activity TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            );

            CREATE INDEX coverage_lookup ON page_coverage(user_id, resource_id, activity, page_start);

            CREATE TABLE practice_batches (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
                curriculum_node_id TEXT REFERENCES curriculum_nodes(id) ON DELETE SET NULL,
                subject TEXT NOT NULL,
                chapter TEXT,
                source TEXT,
                attempted INTEGER NOT NULL CHECK (attempted > 0),
                correct INTEGER NOT NULL CHECK (correct >= 0),
                incorrect INTEGER NOT NULL CHECK (incorrect >= 0),
                skipped INTEGER NOT NULL CHECK (skipped >= 0),
                duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
                accuracy REAL NOT NULL CHECK (accuracy BETWEEN 0 AND 100),
                created_at INTEGER NOT NULL
            );

            CREATE TABLE mistakes (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                practice_batch_id TEXT REFERENCES practice_batches(id) ON DELETE SET NULL,
                curriculum_node_id TEXT REFERENCES curriculum_nodes(id) ON DELETE SET NULL,
                subject TEXT NOT NULL,
                chapter TEXT,
                topic TEXT,
                source TEXT,
                question_reference TEXT,
                submitted_answer TEXT,
                correct_answer TEXT,
                explanation TEXT,
                category TEXT NOT NULL,
                difficulty INTEGER CHECK (difficulty IS NULL OR difficulty BETWEEN 1 AND 5),
                status TEXT NOT NULL DEFAULT 'captured' CHECK (status IN ('captured', 'classified', 'scheduled', 'resolved', 'reopened')),
                repeat_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                resolved_at INTEGER
            );

            CREATE TABLE revision_items (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                curriculum_node_id TEXT REFERENCES curriculum_nodes(id) ON DELETE SET NULL,
                mistake_id TEXT REFERENCES mistakes(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL CHECK (item_type IN ('topic', 'pages', 'notes', 'formula', 'mistake', 'mock_question', 'custom')),
                title TEXT NOT NULL,
                subject TEXT,
                due_at INTEGER NOT NULL,
                interval_days INTEGER NOT NULL DEFAULT 1 CHECK (interval_days >= 0),
                status TEXT NOT NULL DEFAULT 'due' CHECK (status IN ('due', 'scheduled', 'completed', 'suspended')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE revision_attempts (
                id TEXT PRIMARY KEY,
                revision_item_id TEXT NOT NULL REFERENCES revision_items(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                result TEXT NOT NULL CHECK (result IN ('forgotten', 'hard', 'good', 'easy')),
                reviewed_at INTEGER NOT NULL,
                previous_interval_days INTEGER NOT NULL,
                next_interval_days INTEGER NOT NULL
            );

            CREATE TABLE mastery_evidence (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                subject TEXT NOT NULL,
                chapter TEXT,
                curriculum_node_id TEXT REFERENCES curriculum_nodes(id) ON DELETE SET NULL,
                evidence_type TEXT NOT NULL CHECK (evidence_type IN ('practice', 'revision', 'mock', 'coverage')),
                score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
                weight REAL NOT NULL CHECK (weight BETWEEN 0 AND 1),
                source_id TEXT NOT NULL,
                occurred_at INTEGER NOT NULL,
                UNIQUE(evidence_type, source_id)
            );

            CREATE TABLE mastery_snapshots (
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                subject TEXT NOT NULL,
                chapter_key TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
                confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
                formula_version INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(user_id, subject, chapter_key)
            );

            CREATE TABLE mock_attempts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                source TEXT,
                scope TEXT NOT NULL,
                score REAL NOT NULL CHECK (score BETWEEN 0 AND 720),
                max_score REAL NOT NULL DEFAULT 720 CHECK (max_score > 0),
                correct INTEGER,
                incorrect INTEGER,
                skipped INTEGER,
                duration_seconds INTEGER,
                attempted_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE mock_sections (
                id TEXT PRIMARY KEY,
                mock_id TEXT NOT NULL REFERENCES mock_attempts(id) ON DELETE CASCADE,
                subject TEXT NOT NULL,
                score REAL NOT NULL,
                max_score REAL NOT NULL,
                correct INTEGER,
                incorrect INTEGER,
                skipped INTEGER,
                duration_seconds INTEGER
            );

            CREATE TABLE reminder_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                due_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'delivered', 'cancelled', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at INTEGER,
                delivered_at INTEGER,
                last_error TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX due_reminders ON reminder_jobs(status, due_at);

            CREATE TABLE discipline_snapshots (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
                tier TEXT NOT NULL,
                formula_version INTEGER NOT NULL,
                factors_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, period_start, period_end, formula_version)
            );
            """
        )

    @staticmethod
    def _apply_v3(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            ALTER TABLE profiles ADD COLUMN dm_reminders INTEGER NOT NULL DEFAULT 0 CHECK (dm_reminders IN (0, 1));
            ALTER TABLE profiles ADD COLUMN quiet_hours_start TEXT;
            ALTER TABLE profiles ADD COLUMN quiet_hours_end TEXT;
            ALTER TABLE reminder_jobs ADD COLUMN aggregate_type TEXT;
            ALTER TABLE reminder_jobs ADD COLUMN aggregate_id TEXT;
            CREATE INDEX reminder_aggregate ON reminder_jobs(user_id, job_type, aggregate_type, aggregate_id, status);
            """
        )

    @staticmethod
    def _apply_v4(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE lecture_search_cache (
                cache_key TEXT PRIMARY KEY,
                query_text TEXT NOT NULL,
                results_json TEXT NOT NULL,
                fetched_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE saved_lectures (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel_title TEXT,
                url TEXT NOT NULL,
                subject TEXT,
                topic TEXT,
                status TEXT NOT NULL DEFAULT 'saved' CHECK (status IN ('saved', 'planned', 'watching', 'completed', 'archived')),
                saved_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(user_id, video_id)
            );
            """
        )

    @staticmethod
    def _apply_v5(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE official_news (
                id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                source_name TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                published_at INTEGER,
                discovered_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL
            );

            CREATE INDEX official_news_latest
            ON official_news(COALESCE(published_at, discovered_at) DESC);

            CREATE TABLE news_source_runs (
                source_key TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                checked_at INTEGER NOT NULL,
                last_error TEXT
            );
            """
        )

    @staticmethod
    def _apply_v6(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE goals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                subject TEXT,
                metric TEXT NOT NULL,
                target_value REAL NOT NULL CHECK (target_value > 0),
                current_value REAL NOT NULL DEFAULT 0 CHECK (current_value >= 0),
                unit TEXT NOT NULL,
                due_at INTEGER,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'completed', 'cancelled', 'archived')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                completed_at INTEGER
            );

            CREATE INDEX goals_by_user_status ON goals(user_id, status, due_at);
            """
        )

    @staticmethod
    def _apply_v7(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            ALTER TABLE official_news ADD COLUMN source_position INTEGER NOT NULL DEFAULT 9999;
            CREATE INDEX official_news_source_position
            ON official_news(last_seen_at DESC, source_position, source_key);
            """
        )

    @staticmethod
    def emit_event(
        conn: sqlite3.Connection,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        user_id: str | None,
        payload: dict[str, Any],
        occurred_at: int,
    ) -> str:
        event_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO domain_events
            (id, event_type, aggregate_type, aggregate_id, user_id, payload_json, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, event_type, aggregate_type, aggregate_id, user_id, json.dumps(payload), occurred_at),
        )
        return event_id
