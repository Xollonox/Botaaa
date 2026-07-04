"""Shared aiohttp session for the bot.

A single ClientSession is reused across all outbound HTTP calls so we avoid
paying a fresh TLS handshake for every LLM / image request. The session is
created lazily on first use (must be inside a running event loop) and closed
during bot shutdown via close_session().
"""
import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger("misskim")

_session: Optional[aiohttp.ClientSession] = None
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_session() -> aiohttp.ClientSession:
    """Return the process-wide aiohttp ClientSession, creating it on first call.

    Must be awaited from within a running event loop.
    """
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _get_lock():
        if _session is None or _session.closed:
            # A generous connector-level timeout is intentionally omitted; each
            # request passes its own aiohttp.ClientTimeout.
            _session = aiohttp.ClientSession()
            logger.info("Created shared aiohttp ClientSession")
    return _session


async def close_session() -> None:
    """Close the shared session if it exists. Safe to call multiple times."""
    global _session
    if _session is not None and not _session.closed:
        try:
            await _session.close()
            logger.info("Closed shared aiohttp ClientSession")
        except Exception:
            logger.exception("Error closing shared aiohttp ClientSession")
    _session = None
