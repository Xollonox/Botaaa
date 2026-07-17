"""Low-volume, best-effort web search through the open-source ddgs client."""

from __future__ import annotations

import asyncio
import html
import re
import time
from collections import deque
from threading import Lock
from typing import Any, Callable
from urllib.parse import urlparse


OFFICIAL_DOMAINS = frozenset({
    "nta.ac.in", "neet.nta.nic.in", "nmc.org.in", "ncert.nic.in", "mcc.nic.in",
})
STUDY_DOMAINS = OFFICIAL_DOMAINS | frozenset({
    "youtube.com", "youtu.be", "pw.live", "allen.in", "aakash.ac.in", "unacademy.com",
})


class WebSearchError(RuntimeError):
    """A user-safe search failure."""


class SearchRateLimitError(WebSearchError):
    """Raised before the upstream search service is contacted."""


class WebSearchService:
    """Keep ddgs useful for occasional lookups, never as a bulk scraper."""

    def __init__(
        self,
        *,
        user_cooldown_seconds: int = 20,
        user_daily_limit: int = 10,
        global_daily_limit: int = 100,
        search_callable: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        self.user_cooldown_seconds = max(1, int(user_cooldown_seconds))
        self.user_daily_limit = max(1, int(user_daily_limit))
        self.global_daily_limit = max(1, int(global_daily_limit))
        self._user_requests: dict[str, deque[float]] = {}
        self._global_requests: deque[float] = deque()
        self._lock = Lock()
        self._search_callable = search_callable

    async def search(
        self,
        user_id: str,
        query: str,
        *,
        scope: str = "official",
        max_results: int = 5,
        now: float | None = None,
    ) -> list[dict[str, str]]:
        cleaned = " ".join(str(query or "").split())
        if not cleaned:
            raise WebSearchError("Search text is required")
        if len(cleaned) > 200:
            raise WebSearchError("Search text must be 200 characters or fewer")
        scope = str(scope or "official").strip().lower()
        if scope not in {"official", "study", "web"}:
            raise WebSearchError("Choose official, study, or web search")
        count = max(1, min(int(max_results), 8))
        timestamp = float(time.time() if now is None else now)
        self._claim(str(user_id), timestamp)
        domains = None if scope == "web" else OFFICIAL_DOMAINS if scope == "official" else STUDY_DOMAINS
        fetch_count = min(25, max(count * 4, count)) if domains else count
        try:
            rows = await asyncio.to_thread(self._run_search, cleaned, fetch_count, domains)
        except WebSearchError:
            raise
        except Exception as exc:
            raise WebSearchError("Web search is temporarily unavailable") from exc
        return _normalise_results(rows, domains=domains, limit=count)

    def _claim(self, user_id: str, timestamp: float) -> None:
        cutoff = timestamp - 86_400
        with self._lock:
            user_bucket = self._user_requests.setdefault(user_id, deque())
            _trim(user_bucket, cutoff)
            _trim(self._global_requests, cutoff)
            if user_bucket and timestamp - user_bucket[-1] < self.user_cooldown_seconds:
                wait = self.user_cooldown_seconds - (timestamp - user_bucket[-1])
                raise SearchRateLimitError(f"Please wait {max(1, int(wait))}s before searching again")
            if len(user_bucket) >= self.user_daily_limit:
                raise SearchRateLimitError("You reached the web-search limit for today")
            if len(self._global_requests) >= self.global_daily_limit:
                raise SearchRateLimitError("NeetVerse reached its shared web-search limit for today")
            user_bucket.append(timestamp)
            self._global_requests.append(timestamp)

    def _run_search(
        self,
        query: str,
        max_results: int,
        domains: frozenset[str] | None,
    ) -> list[dict[str, Any]]:
        if self._search_callable is not None:
            return self._search_callable(query, max_results=max_results, domains=domains)
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise WebSearchError("The optional ddgs package is not installed") from exc
        try:
            return list(DDGS().text(
                query,
                region="in-en",
                safesearch="moderate",
                max_results=max_results,
            ))
        except Exception as exc:
            raise WebSearchError("The upstream search provider rejected the request") from exc


def _normalise_results(
    rows: list[dict[str, Any]],
    *,
    domains: frozenset[str] | None,
    limit: int,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("href") or raw.get("url") or "").strip()
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme not in {"http", "https"} or not host or url in seen:
            continue
        if domains is not None and not any(host == domain or host.endswith(f".{domain}") for domain in domains):
            continue
        title = _clean_text(raw.get("title"))
        snippet = _clean_text(raw.get("body") or raw.get("snippet"))
        if not title:
            continue
        seen.add(url)
        results.append({
            "title": title[:200],
            "url": url[:1000],
            "domain": host,
            "snippet": snippet[:500],
        })
        if len(results) >= limit:
            break
    return results


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return re.sub(r"<[^>]+>", "", " ".join(text.split())).strip()


def _trim(bucket: deque[float], cutoff: float) -> None:
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
