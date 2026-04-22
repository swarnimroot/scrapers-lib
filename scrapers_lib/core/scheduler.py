"""Persistent SQLite-backed job queue with adaptive per-domain scheduling.

Scheduler owns a single SQLite file that tracks:

- ``jobs`` — URLs to fetch, with source, serialized Anchor list, fetch options,
  priority, status, retry state, next-eligible timestamp.
- ``domain_state`` — per-domain backoff window, consecutive-failure counter,
  cumulative success/failure totals.

It drives a worker loop that claims the next eligible pending job, dispatches
to the registered fetcher, and delivers the result via a consumer-provided
callback. Respects an optional :class:`RateLimiter` for pacing and an optional
:class:`RobotsChecker` for robots.txt compliance.

One worker process per consumer; state survives restart. See
``docs/ARCHITECTURE.md`` §5.2 and §6 for the design narrative.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from pydantic import TypeAdapter

from scrapers_lib.core.rate_limiter import RateLimiter
from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.robots import RobotsChecker
from scrapers_lib.core.schemas import Anchor

logger = logging.getLogger(__name__)


_AnchorListTA: TypeAdapter = TypeAdapter(list[Anchor])


class BlockedError(Exception):
    """Raised by a fetcher when a domain appears to be blocking (429/403/CAPTCHA).

    Triggers an immediate longer domain-wide backoff, distinct from ordinary
    per-job retry. Use for explicit signals; generic transient errors should
    raise regular exceptions and rely on per-job retry.
    """


class Scheduler:
    """SQLite-backed job queue + worker loop with per-domain adaptive backoff."""

    _SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        source TEXT NOT NULL,
        domain TEXT NOT NULL,
        anchors_json TEXT,
        fetch_options_json TEXT,
        priority INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        created_at REAL NOT NULL,
        last_attempt_at REAL,
        next_attempt_at REAL NOT NULL DEFAULT 0,
        error TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_status_next ON jobs(status, next_attempt_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_domain_status ON jobs(domain, status);

    CREATE TABLE IF NOT EXISTS domain_state (
        domain TEXT PRIMARY KEY,
        backoff_until REAL,
        last_success_at REAL,
        last_failure_at REAL,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        total_successes INTEGER NOT NULL DEFAULT 0,
        total_failures INTEGER NOT NULL DEFAULT 0
    );
    """

    def __init__(
        self,
        state_file: str | Path,
        result_sink: Callable[[list], None],
        *,
        rate_limiter: RateLimiter | None = None,
        robots: RobotsChecker | None = None,
        poll_interval: float = 1.0,
        default_max_attempts: int = 3,
        default_retry_backoff_base: float = 30.0,
        default_retry_backoff_max: float = 3600.0,
        domain_backoff_after_failures: int = 3,
        domain_backoff_duration: float = 3600.0,
        blocked_backoff_duration: float = 6 * 3600.0,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._state_file = Path(state_file)
        if self._state_file.parent != Path("."):
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._result_sink = result_sink
        self._rate_limiter = rate_limiter
        self._robots = robots
        self._poll_interval = poll_interval
        self._default_max_attempts = default_max_attempts
        self._default_retry_backoff_base = default_retry_backoff_base
        self._default_retry_backoff_max = default_retry_backoff_max
        self._domain_backoff_after_failures = domain_backoff_after_failures
        self._domain_backoff_duration = domain_backoff_duration
        self._blocked_backoff_duration = blocked_backoff_duration
        self._time = time_fn
        self._sleep = sleep_fn
        self._stopped = False

        self._conn = sqlite3.connect(
            str(self._state_file),
            isolation_level=None,  # autocommit per statement
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._SCHEMA_SQL)

    # ---------------- Public API ----------------

    def enqueue(
        self,
        url: str,
        *,
        source: str,
        anchors: list[Anchor] | None = None,
        priority: int = 1,
        max_attempts: int | None = None,
        **fetch_options: Any,
    ) -> int:
        """Add a job. Returns the assigned job ID."""
        domain = _domain_of(url)
        anchors_json = (
            _AnchorListTA.dump_json(anchors).decode("utf-8") if anchors else None
        )
        options_json = json.dumps(fetch_options) if fetch_options else None
        now = self._time()

        cur = self._conn.execute(
            """
            INSERT INTO jobs
                (url, source, domain, anchors_json, fetch_options_json,
                 priority, status, attempts, max_attempts, created_at, next_attempt_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, 0)
            """,
            (
                url,
                source,
                domain,
                anchors_json,
                options_json,
                priority,
                max_attempts if max_attempts is not None else self._default_max_attempts,
                now,
            ),
        )
        return cur.lastrowid or 0

    def run_worker(
        self, mode: Literal["forever", "until_empty"] = "forever"
    ) -> None:
        """Drain the queue.

        ``forever`` polls indefinitely; call :meth:`stop` to interrupt.
        ``until_empty`` returns when no eligible jobs remain.
        """
        self._stopped = False
        while not self._stopped:
            claimed = self._claim_next_job()
            if claimed is None:
                if mode == "until_empty":
                    return
                self._sleep(self._poll_interval)
                continue
            self._execute_job(claimed)

    def stop(self) -> None:
        """Signal the worker loop to stop at the next iteration."""
        self._stopped = True

    def stats(self) -> dict[str, Any]:
        """Return a summary of jobs by status and per-domain health."""
        status_counts = {
            row["status"]: row["count"]
            for row in self._conn.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            )
        }
        domain_rows = list(
            self._conn.execute(
                """
                SELECT domain, backoff_until, consecutive_failures,
                       total_successes, total_failures,
                       last_success_at, last_failure_at
                FROM domain_state
                """
            )
        )
        domains = {
            row["domain"]: {
                "backoff_until": row["backoff_until"],
                "consecutive_failures": row["consecutive_failures"],
                "total_successes": row["total_successes"],
                "total_failures": row["total_failures"],
                "last_success_at": row["last_success_at"],
                "last_failure_at": row["last_failure_at"],
            }
            for row in domain_rows
        }
        return {"status_counts": status_counts, "domains": domains}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Scheduler:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------------- Internal ----------------

    def _claim_next_job(self) -> sqlite3.Row | None:
        """Find and atomically claim the next eligible pending job."""
        now = self._time()
        cursor = self._conn.execute(
            """
            SELECT j.*
            FROM jobs j
            LEFT JOIN domain_state ds ON ds.domain = j.domain
            WHERE j.status = 'pending'
              AND j.next_attempt_at <= ?
              AND (ds.backoff_until IS NULL OR ds.backoff_until <= ?)
            ORDER BY j.priority DESC, j.next_attempt_at ASC
            """,
            (now, now),
        )
        for row in cursor:
            # robots.txt check
            if self._robots is not None and not self._robots.allowed(row["url"]):
                logger.info(
                    "robots.txt disallows %s; marking job %d failed",
                    row["url"],
                    row["id"],
                )
                self._mark_failed(row["id"], "robots.txt disallowed", retry=False)
                continue

            # rate limiter check (consumes a token if available)
            if self._rate_limiter is not None and not self._rate_limiter.try_acquire(
                row["domain"]
            ):
                continue

            # atomically claim
            changed = self._conn.execute(
                """
                UPDATE jobs
                SET status='in_progress', last_attempt_at=?, attempts=attempts+1
                WHERE id=? AND status='pending'
                """,
                (now, row["id"]),
            ).rowcount
            if changed == 1:
                return self._get_job(row["id"])
        return None

    def _execute_job(self, job: sqlite3.Row) -> None:
        try:
            fetcher = get_fetcher(job["source"])
        except KeyError as e:
            logger.error(
                "no fetcher for source %r; marking job %d failed",
                job["source"],
                job["id"],
            )
            self._mark_failed(job["id"], f"no fetcher: {e}", retry=False)
            return

        anchors = (
            _AnchorListTA.validate_json(job["anchors_json"])
            if job["anchors_json"]
            else None
        )
        options = (
            json.loads(job["fetch_options_json"]) if job["fetch_options_json"] else {}
        )

        try:
            result = fetcher(job["url"], anchors=anchors, **options)
        except BlockedError as e:
            logger.warning(
                "blocked on %s: %s; extending domain backoff", job["url"], e
            )
            self._extend_domain_backoff(
                job["domain"], self._blocked_backoff_duration, str(e)
            )
            self._mark_failed(job["id"], f"blocked: {e}", retry=True)
            return
        except Exception as e:
            logger.warning("fetcher error on %s: %s", job["url"], e)
            self._bump_domain_failure(job["domain"], str(e))
            self._mark_failed(job["id"], str(e), retry=True)
            return

        # Success
        self._mark_done(job["id"])
        self._bump_domain_success(job["domain"])

        if result:
            try:
                self._result_sink(result)
            except Exception as e:
                # Sink errors are logged loudly but do NOT cause retry — the
                # fetch itself succeeded; sink reliability is consumer-owned.
                logger.error("result_sink raised on job %d: %s", job["id"], e)

    def _mark_done(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE jobs SET status='done', error=NULL WHERE id=?", (job_id,)
        )

    def _mark_failed(self, job_id: int, error: str, *, retry: bool) -> None:
        job = self._get_job(job_id)
        if retry and job["attempts"] < job["max_attempts"]:
            # exponential retry backoff (per-job, separate from per-domain backoff)
            exponent = max(0, job["attempts"] - 1)
            backoff = min(
                self._default_retry_backoff_max,
                self._default_retry_backoff_base * (2**exponent),
            )
            self._conn.execute(
                """
                UPDATE jobs
                SET status='pending', next_attempt_at=?, error=?
                WHERE id=?
                """,
                (self._time() + backoff, error, job_id),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET status='failed', error=? WHERE id=?",
                (error, job_id),
            )

    def _get_job(self, job_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert row is not None
        return row

    def _bump_domain_success(self, domain: str) -> None:
        now = self._time()
        self._conn.execute(
            """
            INSERT INTO domain_state
                (domain, last_success_at, total_successes,
                 consecutive_failures, backoff_until)
            VALUES (?, ?, 1, 0, NULL)
            ON CONFLICT(domain) DO UPDATE SET
                last_success_at=excluded.last_success_at,
                total_successes=total_successes+1,
                consecutive_failures=0,
                backoff_until=NULL
            """,
            (domain, now),
        )

    def _bump_domain_failure(self, domain: str, error: str) -> None:
        now = self._time()
        self._conn.execute(
            """
            INSERT INTO domain_state
                (domain, last_failure_at, total_failures, consecutive_failures)
            VALUES (?, ?, 1, 1)
            ON CONFLICT(domain) DO UPDATE SET
                last_failure_at=excluded.last_failure_at,
                total_failures=total_failures+1,
                consecutive_failures=consecutive_failures+1
            """,
            (domain, now),
        )
        row = self._conn.execute(
            "SELECT consecutive_failures FROM domain_state WHERE domain=?",
            (domain,),
        ).fetchone()
        if row and row["consecutive_failures"] >= self._domain_backoff_after_failures:
            self._extend_domain_backoff(
                domain, self._domain_backoff_duration, error
            )

    def _extend_domain_backoff(
        self, domain: str, duration: float, reason: str
    ) -> None:
        until = self._time() + duration
        # Ensure row exists so UPDATE hits
        self._conn.execute(
            """
            INSERT INTO domain_state (domain, backoff_until)
            VALUES (?, ?)
            ON CONFLICT(domain) DO UPDATE SET backoff_until=excluded.backoff_until
            """,
            (domain, until),
        )
        logger.info(
            "domain %s backed off for %.0fs (%s)", domain, duration, reason
        )


def _domain_of(url: str) -> str:
    """Extract the host[:port] from ``url``. Falls back to the raw url if parsing fails."""
    return urlparse(url).netloc or url
