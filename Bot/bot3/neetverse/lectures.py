"""Quota-conscious YouTube Data API v3 lecture discovery."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from html import unescape
from typing import Any

import aiohttp

from .database import Database


class LectureError(RuntimeError):
    pass


class LectureService:
    def __init__(self, database: Database, *, api_key: str, base_url: str) -> None:
        self.database = database
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def search(
        self,
        *,
        subject: str,
        topic: str,
        language: str = "",
        lecture_type: str = "detailed",
        max_results: int = 5,
        now: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise LectureError("YouTube lecture discovery is not configured")
        if not subject.strip() or not topic.strip():
            raise LectureError("Subject and topic are required")
        timestamp = int(time.time() if now is None else now)
        count = max(1, min(int(max_results), 10))
        query = " ".join(
            part for part in (
                "NEET", subject.strip(), topic.strip(),
                "one shot revision" if lecture_type == "revision" else "full lecture",
                language.strip(),
            ) if part
        )
        cache_key = hashlib.sha256(f"{query.lower()}|{count}".encode()).hexdigest()
        cached = self._cached(cache_key, timestamp)
        if cached is not None:
            return cached
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/search",
                params={
                    "key": self.api_key,
                    "part": "snippet",
                    "type": "video",
                    "q": query,
                    "maxResults": count,
                    "order": "relevance",
                    "safeSearch": "strict",
                    "videoEmbeddable": "true",
                    "regionCode": "IN",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                body = await response.text()
                if response.status != 200:
                    raise LectureError(f"YouTube search failed ({response.status})")
                search_data = json.loads(body)
            items = search_data.get("items", [])
            video_ids = [str(item.get("id", {}).get("videoId", "")) for item in items]
            video_ids = [value for value in video_ids if value]
            details: dict[str, dict[str, Any]] = {}
            if video_ids:
                async with session.get(
                    f"{self.base_url}/videos",
                    params={
                        "key": self.api_key,
                        "part": "contentDetails,statistics,status",
                        "id": ",".join(video_ids),
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    body = await response.text()
                    if response.status == 200:
                        data = json.loads(body)
                        details = {str(item.get("id")): item for item in data.get("items", [])}
        except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as exc:
            raise LectureError("YouTube is temporarily unavailable") from exc

        results: list[dict[str, Any]] = []
        by_id = {str(item.get("id", {}).get("videoId", "")): item for item in items}
        for video_id in video_ids:
            item = by_id.get(video_id, {})
            snippet = item.get("snippet", {})
            detail = details.get(video_id, {})
            status = detail.get("status", {})
            if status and (status.get("privacyStatus") != "public" or status.get("embeddable") is False):
                continue
            statistics = detail.get("statistics", {})
            results.append(
                {
                    "video_id": video_id,
                    "title": unescape(str(snippet.get("title", "Untitled"))),
                    "channel_title": unescape(str(snippet.get("channelTitle", "Unknown channel"))),
                    "description": unescape(str(snippet.get("description", "")))[:300],
                    "published_at": str(snippet.get("publishedAt", "")),
                    "thumbnail_url": str(snippet.get("thumbnails", {}).get("medium", {}).get("url", "")),
                    "duration_seconds": _iso_duration_seconds(str(detail.get("contentDetails", {}).get("duration", ""))),
                    "view_count": int(statistics.get("viewCount", 0) or 0),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "selection_reason": f"Matched NEET {subject.strip()} • {topic.strip()} • {lecture_type}",
                }
            )
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO lecture_search_cache(cache_key, query_text, results_json, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET results_json=excluded.results_json,
                    fetched_at=excluded.fetched_at, expires_at=excluded.expires_at
                """,
                (cache_key, query, json.dumps(results), timestamp, timestamp + 6 * 3600),
            )
        return results

    def save(self, user_id: str, lecture: dict[str, Any], *, subject: str = "", topic: str = "", now: int | None = None) -> dict[str, Any]:
        video_id = str(lecture.get("video_id", "")).strip()
        if not video_id:
            raise LectureError("Lecture has no YouTube video ID")
        timestamp = int(time.time() if now is None else now)
        saved_id = str(uuid.uuid4())
        with self.database.transaction(immediate=True) as conn:
            if conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (str(user_id),)).fetchone() is None:
                raise LectureError("Run /start before saving lectures")
            conn.execute(
                """
                INSERT INTO saved_lectures(
                    id, user_id, video_id, title, channel_title, url, subject, topic, saved_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    title=excluded.title, channel_title=excluded.channel_title,
                    subject=excluded.subject, topic=excluded.topic, updated_at=excluded.updated_at
                """,
                (
                    saved_id, str(user_id), video_id, str(lecture.get("title", "Untitled"))[:300],
                    str(lecture.get("channel_title", ""))[:200], str(lecture.get("url", ""))[:500],
                    subject.strip()[:100] or None, topic.strip()[:150] or None, timestamp, timestamp,
                ),
            )
        return {"video_id": video_id, "title": lecture.get("title"), "url": lecture.get("url")}

    def saved(self, user_id: str, *, include_archived: bool = False) -> list[dict[str, Any]]:
        condition = "user_id=?" if include_archived else "user_id=? AND status!='archived'"
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM saved_lectures WHERE {condition} ORDER BY updated_at DESC LIMIT 25",
                (str(user_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_status(self, user_id: str, token: str, status: str, *, now: int | None = None) -> dict[str, Any]:
        state = status.strip().lower()
        if state not in {"saved", "planned", "watching", "completed", "archived"}:
            raise LectureError("Invalid lecture status")
        timestamp = int(time.time() if now is None else now)
        with self.database.transaction(immediate=True) as conn:
            rows = conn.execute(
                "SELECT * FROM saved_lectures WHERE user_id=? AND (id LIKE ? OR video_id=?) LIMIT 2",
                (str(user_id), f"{token.strip()}%", token.strip()),
            ).fetchall()
            if not rows:
                raise LectureError("Saved lecture not found")
            if len(rows) > 1:
                raise LectureError("Lecture ID is ambiguous; provide more characters")
            conn.execute("UPDATE saved_lectures SET status=?, updated_at=? WHERE id=?", (state, timestamp, rows[0]["id"]))
            row = conn.execute("SELECT * FROM saved_lectures WHERE id=?", (rows[0]["id"],)).fetchone()
        return dict(row)

    def _cached(self, cache_key: str, timestamp: int) -> list[dict[str, Any]] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT results_json FROM lecture_search_cache WHERE cache_key=? AND expires_at>?",
                (cache_key, timestamp),
            ).fetchone()
        return json.loads(row["results_json"]) if row else None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session


def _iso_duration_seconds(value: str) -> int | None:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds
