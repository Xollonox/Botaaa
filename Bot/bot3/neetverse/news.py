"""Verified-source NEET news ingestion and retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import html
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from .database import Database


OFFICIAL_SOURCES = {
    "nta_neet": {
        "name": "National Testing Agency — NEET",
        "url": "https://neet.nta.nic.in/document-category/public-notices/",
        "domains": {"neet.nta.nic.in", "nta.ac.in", "www.nta.ac.in", "cdnbbsr.s3waas.gov.in"},
    },
    "mcc_ug": {
        "name": "Medical Counselling Committee",
        "url": "https://mcc.nic.in/current-events-ug/",
        "domains": {"mcc.nic.in", "cdnbbsr.s3waas.gov.in"},
    },
}


class NewsError(RuntimeError):
    pass


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "table":
            self._table_depth += 1
        if lowered == "a" and self._table_depth:
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None
            self._text = []
        if lowered == "table" and self._table_depth:
            self._table_depth -= 1


class OfficialNewsService:
    def __init__(self, database: Database, *, timeout_seconds: int = 25) -> None:
        self.database = database
        self.timeout_seconds = timeout_seconds
        self._session: aiohttp.ClientSession | None = None
        self._sync_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def sync_all(self, *, now: int | None = None) -> dict[str, int]:
        timestamp = int(time.time() if now is None else now)
        results: dict[str, int] = {}
        async with self._sync_lock:
            for key, source in OFFICIAL_SOURCES.items():
                try:
                    items = await self._fetch_source(source)
                    results[key] = self._store(key, source["name"], items, timestamp)
                    self._record_run(key, "success", len(items), timestamp, None)
                except Exception as exc:
                    self._record_run(key, "failed", 0, timestamp, str(exc)[:500])
                    results[key] = 0
        return results

    async def _fetch_source(self, source: dict[str, Any]) -> list[dict[str, str]]:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "NeetVerse/1.0"})
        async with self._session.get(source["url"]) as response:
            if response.status != 200:
                raise NewsError(f"Official source returned HTTP {response.status}")
            body = await response.text()
        parser = _LinkParser()
        parser.feed(body)
        seen: set[str] = set()
        items: list[dict[str, str]] = []
        for href, raw_title in parser.links:
            url = urljoin(source["url"], href.strip())
            title = " ".join(html.unescape(raw_title).split())
            host = (urlparse(url).hostname or "").lower()
            if host not in source["domains"] or not _looks_like_notice(title, url) or url in seen:
                continue
            seen.add(url)
            items.append({"title": title[:500], "url": url})
        return items[:100]

    def _store(self, source_key: str, source_name: str, items: list[dict[str, str]], timestamp: int) -> int:
        with self.database.transaction(immediate=True) as conn:
            for position, item in enumerate(items):
                item_id = hashlib.sha256(item["url"].encode()).hexdigest()
                conn.execute(
                    """
                    INSERT INTO official_news
                    (id, source_key, source_name, title, url, discovered_at, last_seen_at, source_position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        title=excluded.title, source_name=excluded.source_name,
                        source_key=excluded.source_key, last_seen_at=excluded.last_seen_at,
                        source_position=excluded.source_position
                    """,
                    (item_id, source_key, source_name, item["title"], item["url"], timestamp, timestamp, position),
                )
        return len(items)

    def latest(self, *, limit: int = 8) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM official_news
                ORDER BY last_seen_at DESC, source_position, source_key LIMIT ?
                """,
                (max(1, min(20, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]

    def source_status(self) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM news_source_runs ORDER BY source_key").fetchall()
        return [dict(row) for row in rows]

    def _record_run(self, source_key: str, status: str, count: int, timestamp: int, error: str | None) -> None:
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO news_source_runs(source_key, status, item_count, checked_at, last_error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET status=excluded.status,
                    item_count=excluded.item_count, checked_at=excluded.checked_at,
                    last_error=excluded.last_error
                """,
                (source_key, status, count, timestamp, error),
            )


def _looks_like_notice(title: str, url: str) -> bool:
    if len(title) < 12 or len(title) > 500:
        return False
    lowered = f"{title} {url}".lower()
    ignored = ("skip to", "screen reader", "facebook", "twitter", "instagram", "youtube", "contact us")
    if any(value in lowered for value in ignored):
        return False
    signals = ("neet", "notice", "result", "answer key", "admit", "counselling", "counseling", "seat", "schedule", ".pdf")
    return any(value in lowered for value in signals)
