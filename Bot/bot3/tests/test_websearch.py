from __future__ import annotations

import asyncio

import pytest

from neetverse.websearch import SearchRateLimitError, WebSearchService


def test_search_filters_official_domains_and_caps_results() -> None:
    def fake(_query, *, max_results, domains):
        assert max_results == 25
        assert "nmc.org.in" in domains
        return [
            {"title": "NMC notice", "href": "https://www.nmc.org.in/notice", "body": "Official"},
            {"title": "Random", "href": "https://example.com/random", "body": "No"},
            {"title": "NTA notice", "href": "https://nta.ac.in/notice", "body": "Official"},
        ]

    service = WebSearchService(search_callable=fake, user_cooldown_seconds=1)
    rows = asyncio.run(service.search("1", "NEET syllabus", scope="official", max_results=8, now=100))

    assert [row["domain"] for row in rows] == ["nmc.org.in", "nta.ac.in"]
    assert rows[0]["snippet"] == "Official"


def test_search_has_user_cooldown_and_daily_cap_before_upstream_call() -> None:
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(True)
        return []

    service = WebSearchService(
        search_callable=fake,
        user_cooldown_seconds=20,
        user_daily_limit=2,
        global_daily_limit=10,
    )
    asyncio.run(service.search("1", "first", scope="web", now=100))
    with pytest.raises(SearchRateLimitError, match="wait"):
        asyncio.run(service.search("1", "too soon", scope="web", now=110))
    asyncio.run(service.search("1", "second", scope="web", now=121))
    with pytest.raises(SearchRateLimitError, match="today"):
        asyncio.run(service.search("1", "third", scope="web", now=142))
    assert len(calls) == 2
