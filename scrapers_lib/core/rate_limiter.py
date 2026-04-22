"""Per-domain token-bucket rate limiter.

Two layers:

- :class:`Bucket` is the pure token-bucket logic. Time is passed in as an
  argument so it's easy to test without real delays.
- :class:`RateLimiter` is the wall-clock wrapper. Maps domain strings to
  buckets, reads from :func:`time.monotonic`, and provides the API the
  Scheduler uses to pace requests.

Intended use: when the Scheduler picks up a job, it calls
:meth:`RateLimiter.try_acquire` for the job's domain. If a token is
available, the request proceeds and the token is consumed. If not, the
Scheduler can ask :meth:`RateLimiter.wait_seconds` how long until the
next token and pick a different domain's job in the meantime.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Bucket:
    """Pure token-bucket logic. ``capacity`` tokens max, ``refill_per_sec`` refill rate.

    Time is supplied by the caller (use :func:`time.monotonic` in production,
    explicit values in tests). Not thread-safe on its own; the owning
    :class:`RateLimiter` provides locking.
    """

    capacity: float
    refill_per_sec: float
    tokens: float = field(init=False)
    last_refill: float = 0.0

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def _refill(self, now: float) -> None:
        if self.last_refill == 0.0:
            self.last_refill = now
            return
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        self.last_refill = now

    def try_acquire(self, now: float) -> bool:
        """Try to consume one token. Returns True if acquired, False otherwise."""
        self._refill(now)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def wait_seconds(self, now: float) -> float:
        """Seconds until the next token becomes available. Zero if one is ready."""
        self._refill(now)
        if self.tokens >= 1.0:
            return 0.0
        if self.refill_per_sec <= 0.0:
            return float("inf")
        return (1.0 - self.tokens) / self.refill_per_sec


class RateLimiter:
    """Per-domain token-bucket rate limiter using wall-clock time.

    Default behavior (when ``configure`` hasn't been called for a domain)
    uses ``default_rps`` requests/sec with ``default_burst`` burst capacity.
    """

    def __init__(self, default_rps: float = 1.0, default_burst: int = 1) -> None:
        self._default_rps = default_rps
        self._default_burst = float(default_burst)
        self._buckets: dict[str, Bucket] = {}
        self._lock = threading.Lock()

    def configure(self, domain: str, *, rps: float, burst: int = 1) -> None:
        """Set ``rps`` (requests/sec) and ``burst`` capacity for ``domain``.

        Replaces any previous config for that domain. Resets the bucket to full.
        """
        if rps <= 0:
            raise ValueError("rps must be positive")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        with self._lock:
            self._buckets[domain] = Bucket(capacity=float(burst), refill_per_sec=rps)

    def try_acquire(self, domain: str) -> bool:
        """Try to consume one token for ``domain``. Returns True if acquired."""
        with self._lock:
            bucket = self._get_or_create(domain)
            return bucket.try_acquire(time.monotonic())

    def wait_seconds(self, domain: str) -> float:
        """Seconds until the next token is available for ``domain``."""
        with self._lock:
            bucket = self._get_or_create(domain)
            return bucket.wait_seconds(time.monotonic())

    def _get_or_create(self, domain: str) -> Bucket:
        bucket = self._buckets.get(domain)
        if bucket is None:
            bucket = Bucket(
                capacity=self._default_burst,
                refill_per_sec=self._default_rps,
            )
            self._buckets[domain] = bucket
        return bucket
