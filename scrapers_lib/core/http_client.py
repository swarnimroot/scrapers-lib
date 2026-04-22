"""httpx-based HTTP client with retry/backoff and user-agent rotation.

Retries on:

- ``429 Too Many Requests`` — respects ``Retry-After`` when present.
- ``503 Service Unavailable``.
- :class:`httpx.TransportError` and :class:`httpx.TimeoutException` (network errors).

Backoff is exponential with jitter, capped at ``backoff_max``. Maximum retry
count is configurable.

This client is used by Tier 1 fetchers (RSS, article body, Reddit fallbacks,
BestBuy API) where a simple HTTP library is sufficient. Tier 2/3 uses
Playwright (see :mod:`scrapers_lib.core.playwright_base`) because those pages
need JS execution.

For testing, inject an :class:`httpx.BaseTransport` (e.g. :class:`httpx.MockTransport`)
via ``transport=``, and a no-op ``sleep_fn`` to skip real sleeps.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)


class HttpClient:
    """httpx ``Client`` wrapper with retry, backoff, and UA rotation."""

    def __init__(
        self,
        *,
        user_agents: tuple[str, ...] | list[str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._user_agents: tuple[str, ...] = (
            tuple(user_agents) if user_agents else DEFAULT_USER_AGENTS
        )
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True, transport=transport
        )

    def get(
        self, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> httpx.Response:
        return self._request("GET", url, headers=headers, **kwargs)

    def post(
        self, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> httpx.Response:
        return self._request("POST", url, headers=headers, **kwargs)

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        merged_headers: dict[str, str] = {"User-Agent": random.choice(self._user_agents)}
        if headers:
            merged_headers.update(headers)

        resp: httpx.Response | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(
                    method, url, headers=merged_headers, **kwargs
                )
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if attempt >= self._max_retries:
                    raise
                wait = self._backoff(attempt)
                logger.info(
                    "network error on %s: %s; retry %d/%d after %.1fs",
                    url,
                    e,
                    attempt + 1,
                    self._max_retries,
                    wait,
                )
                self._sleep(wait)
                continue

            if resp.status_code in (429, 503) and attempt < self._max_retries:
                retry_after = self._parse_retry_after(resp)
                wait = retry_after if retry_after is not None else self._backoff(attempt)
                logger.info(
                    "%d on %s; retry %d/%d after %.1fs",
                    resp.status_code,
                    url,
                    attempt + 1,
                    self._max_retries,
                    wait,
                )
                self._sleep(wait)
                continue

            return resp

        # Exhausted retries on 429/503; return the last response
        assert resp is not None
        return resp

    def _backoff(self, attempt: int) -> float:
        base = min(self._backoff_max, self._backoff_base * (2**attempt))
        jitter = random.uniform(0, base * 0.25)
        return base + jitter

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        header = resp.headers.get("Retry-After")
        if not header:
            return None
        try:
            return float(header)
        except ValueError:
            # Could be an HTTP-date; fall back to our exponential backoff
            return None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
