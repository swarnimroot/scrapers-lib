"""robots.txt awareness with per-domain caching.

On first request to a domain, fetches ``{origin}/robots.txt`` and parses it
with :mod:`urllib.robotparser`. Subsequent checks reuse the cached parser.

If robots.txt is unreachable (network error, 4xx, 5xx), the checker
assumes allow-all — matching common practice. Consumers who want to
override robots.txt checks entirely do so at the call site by skipping
this checker (the Scheduler exposes ``ignore_robots=True`` per job).

The library itself defaults to respecting robots.txt.
"""

from __future__ import annotations

import logging
import urllib.robotparser
from typing import Callable
from urllib.parse import urlparse

import httpx

from scrapers_lib._version import __version__

logger = logging.getLogger(__name__)


FetchFn = Callable[[str, str], tuple[int, str]]
"""Callable signature: ``(url, user_agent) -> (status_code, body)``."""


class RobotsChecker:
    """robots.txt-aware URL checker with per-origin caching.

    Default fetcher uses :mod:`httpx`; tests can inject a ``fetch_fn`` that
    returns canned ``(status, body)`` tuples to avoid network.
    """

    def __init__(
        self,
        *,
        user_agent: str = f"scrapers-lib/{__version__}",
        timeout: float = 10.0,
        fetch_fn: FetchFn | None = None,
    ) -> None:
        self._ua = user_agent
        self._timeout = timeout
        self._fetch_fn = fetch_fn if fetch_fn is not None else self._default_fetch
        # None value means "fetched and unavailable → assume allow-all"
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        """Return ``True`` if robots.txt allows the configured user-agent to fetch ``url``."""
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            # Malformed URL — let the actual fetcher complain, not this checker
            return True

        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._get_parser(origin)
        if rp is None:
            return True
        return rp.can_fetch(self._ua, url)

    def _get_parser(self, origin: str) -> urllib.robotparser.RobotFileParser | None:
        if origin in self._parsers:
            return self._parsers[origin]

        robots_url = f"{origin}/robots.txt"
        try:
            status, body = self._fetch_fn(robots_url, self._ua)
        except Exception as e:
            logger.debug(
                "robots.txt fetch failed for %s: %s; assuming allow-all", robots_url, e
            )
            self._parsers[origin] = None
            return None

        if status >= 400:
            logger.debug(
                "robots.txt at %s returned %d; assuming allow-all", robots_url, status
            )
            self._parsers[origin] = None
            return None

        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.splitlines())
        self._parsers[origin] = rp
        return rp

    def _default_fetch(self, url: str, user_agent: str) -> tuple[int, str]:
        resp = httpx.get(
            url, timeout=self._timeout, headers={"User-Agent": user_agent}
        )
        return resp.status_code, resp.text
