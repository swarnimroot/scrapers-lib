"""Unit tests for scrapers_lib.core.scheduler."""

from __future__ import annotations

from typing import Any

import pytest

from scrapers_lib.core import registry as _registry_mod
from scrapers_lib.core.rate_limiter import RateLimiter
from scrapers_lib.core.registry import register_fetcher
from scrapers_lib.core.robots import RobotsChecker
from scrapers_lib.core.scheduler import BlockedError, Scheduler, _domain_of
from scrapers_lib.core.schemas import Anchor, AttributionRegex


class FakeClock:
    """Injected clock for deterministic time in tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def time(self) -> float:
        return self.t

    def sleep(self, duration: float) -> None:
        self.t += duration


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot-and-restore the registry so tests here don't leak or stomp.

    Scheduler tests register fake fetchers as needed; snapshotting preserves
    any real fetchers (``tier2.dell``, etc.) that were registered at
    import time elsewhere in the run.
    """
    snapshot = dict(_registry_mod._registry)
    _registry_mod._registry.clear()
    yield
    _registry_mod._registry.clear()
    _registry_mod._registry.update(snapshot)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sink():
    """Collecting result sink."""
    return []


@pytest.fixture
def scheduler(tmp_path, clock, sink):
    sched = Scheduler(
        state_file=tmp_path / "jobs.sqlite",
        result_sink=sink.append,
        poll_interval=0.0,
        default_retry_backoff_base=10.0,
        domain_backoff_after_failures=3,
        domain_backoff_duration=3600.0,
        time_fn=clock.time,
        sleep_fn=clock.sleep,
    )
    yield sched
    sched.close()


class TestDomainOf:
    def test_extracts_netloc(self):
        assert _domain_of("https://example.com/path") == "example.com"

    def test_includes_port(self):
        assert _domain_of("https://example.com:8080/path") == "example.com:8080"

    def test_falls_back_on_malformed(self):
        assert _domain_of("not-a-url") == "not-a-url"


class TestEnqueue:
    def test_returns_incrementing_ids(self, scheduler):
        register_fetcher("test", lambda url, anchors=None, **opts: [])
        id1 = scheduler.enqueue("https://a.com/x", source="test")
        id2 = scheduler.enqueue("https://a.com/y", source="test")
        assert id2 > id1

    def test_stores_domain(self, scheduler):
        register_fetcher("test", lambda url, anchors=None, **opts: [])
        scheduler.enqueue("https://example.com/path", source="test")
        stats = scheduler.stats()
        assert stats["status_counts"]["pending"] == 1

    def test_serializes_anchors(self, scheduler):
        register_fetcher("test", lambda url, anchors=None, **opts: anchors or [])
        anchor = Anchor(
            anchor_id="foo",
            anchor_type="topic",
            name="Foo",
            attribution_regex=AttributionRegex(primary=["foo"]),
        )
        scheduler.enqueue("https://a.com/x", source="test", anchors=[anchor])
        # Will be deserialized inside _execute_job; just verify enqueue works
        assert scheduler.stats()["status_counts"]["pending"] == 1


class TestWorkerSuccess:
    def test_runs_single_job_to_completion(self, scheduler, sink):
        register_fetcher(
            "test", lambda url, anchors=None, **opts: [{"url": url, "ok": True}]
        )
        scheduler.enqueue("https://a.com/x", source="test")
        scheduler.run_worker(mode="until_empty")

        assert scheduler.stats()["status_counts"].get("done") == 1
        assert len(sink) == 1
        assert sink[0][0]["url"] == "https://a.com/x"

    def test_runs_multiple_jobs(self, scheduler, sink):
        register_fetcher("test", lambda url, anchors=None, **opts: [url])
        for i in range(5):
            scheduler.enqueue(f"https://a.com/x{i}", source="test")
        scheduler.run_worker(mode="until_empty")

        assert scheduler.stats()["status_counts"].get("done") == 5
        assert len(sink) == 5

    def test_empty_result_not_passed_to_sink(self, scheduler, sink):
        register_fetcher("test", lambda url, anchors=None, **opts: [])
        scheduler.enqueue("https://a.com/x", source="test")
        scheduler.run_worker(mode="until_empty")

        assert scheduler.stats()["status_counts"].get("done") == 1
        assert sink == []


def _drain_with_retries(scheduler, clock, max_iters: int = 10, advance: float = 3600.0):
    """Repeatedly run until_empty, advancing the fake clock past retry backoffs.

    Needed because ``until_empty`` returns as soon as no immediately-eligible
    job exists — scheduled retries sit with a future ``next_attempt_at`` and
    would otherwise be skipped.
    """
    for _ in range(max_iters):
        scheduler.run_worker(mode="until_empty")
        counts = scheduler.stats()["status_counts"]
        pending = counts.get("pending", 0)
        if pending == 0:
            return
        clock.t += advance


class TestWorkerFailure:
    def test_retry_on_exception(self, scheduler, sink, clock):
        attempts = {"n": 0}

        def flaky(url, anchors=None, **opts):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("transient")
            return [{"url": url}]

        register_fetcher("test", flaky)
        scheduler.enqueue("https://a.com/x", source="test")
        _drain_with_retries(scheduler, clock)

        assert attempts["n"] == 3
        assert scheduler.stats()["status_counts"].get("done") == 1
        assert len(sink) == 1

    def test_max_attempts_exhausted_marks_failed(self, scheduler, clock):
        def always_fails(url, anchors=None, **opts):
            raise RuntimeError("nope")

        register_fetcher("test", always_fails)
        scheduler.enqueue(
            "https://a.com/x", source="test", max_attempts=2
        )
        _drain_with_retries(scheduler, clock)

        counts = scheduler.stats()["status_counts"]
        assert counts.get("failed") == 1
        assert counts.get("done", 0) == 0

    def test_unknown_source_fails_without_retry(self, scheduler):
        # No fetcher registered for "nope"
        scheduler.enqueue("https://a.com/x", source="nope")
        scheduler.run_worker(mode="until_empty")

        counts = scheduler.stats()["status_counts"]
        assert counts.get("failed") == 1


class TestDomainBackoff:
    def test_consecutive_failures_trigger_backoff(self, scheduler, clock):
        def always_fails(url, anchors=None, **opts):
            raise RuntimeError("nope")

        register_fetcher("test", always_fails)
        # 3 jobs on same domain; all will fail → domain backoff kicks in
        for i in range(3):
            scheduler.enqueue(
                f"https://a.com/x{i}", source="test", max_attempts=1
            )
        scheduler.run_worker(mode="until_empty")

        stats = scheduler.stats()
        assert "a.com" in stats["domains"]
        assert stats["domains"]["a.com"]["backoff_until"] is not None
        assert stats["domains"]["a.com"]["consecutive_failures"] == 3

    def test_blocked_error_triggers_immediate_long_backoff(
        self, scheduler, clock
    ):
        def blocked(url, anchors=None, **opts):
            raise BlockedError("403 from server")

        register_fetcher("test", blocked)
        scheduler.enqueue(
            "https://a.com/x", source="test", max_attempts=1
        )
        scheduler.run_worker(mode="until_empty")

        stats = scheduler.stats()
        backoff_until = stats["domains"]["a.com"]["backoff_until"]
        assert backoff_until is not None
        # blocked_backoff_duration defaults to 6h = 21600s; should be >> regular
        assert backoff_until - clock.t > 3600

    def test_success_resets_consecutive_failures(self, scheduler, clock):
        calls = {"n": 0}

        def flaky(url, anchors=None, **opts):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("nope")
            return [url]

        register_fetcher("test", flaky)
        scheduler.enqueue("https://a.com/x", source="test", max_attempts=5)
        _drain_with_retries(scheduler, clock)

        stats = scheduler.stats()
        assert stats["domains"]["a.com"]["consecutive_failures"] == 0
        assert stats["domains"]["a.com"]["total_successes"] == 1


class TestRateLimiter:
    def test_rate_limited_jobs_skipped_until_token_available(
        self, tmp_path, clock, sink
    ):
        rl = RateLimiter(default_rps=1.0, default_burst=1)
        sched = Scheduler(
            state_file=tmp_path / "jobs.sqlite",
            result_sink=sink.append,
            rate_limiter=rl,
            poll_interval=0.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )
        register_fetcher("test", lambda url, anchors=None, **opts: [url])

        # Enqueue two jobs same domain; only one token → second waits
        sched.enqueue("https://a.com/x", source="test")
        sched.enqueue("https://a.com/y", source="test")
        sched.run_worker(mode="until_empty")

        # With fake clock advancing via sleep, both should complete
        # (clock.sleep(poll_interval) but poll_interval=0 … so time doesn't
        # advance and rate limiter stays empty after first acquire).
        # Result: first succeeds, second stays pending.
        counts = sched.stats()["status_counts"]
        assert counts.get("done") == 1
        assert counts.get("pending") == 1
        sched.close()


class TestRobots:
    def test_disallowed_url_marked_failed_no_retry(
        self, tmp_path, clock, sink
    ):
        def fetch_robots(url, ua):
            return (200, "User-agent: *\nDisallow: /\n")

        robots = RobotsChecker(fetch_fn=fetch_robots)
        sched = Scheduler(
            state_file=tmp_path / "jobs.sqlite",
            result_sink=sink.append,
            robots=robots,
            poll_interval=0.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )
        register_fetcher("test", lambda url, anchors=None, **opts: [url])

        sched.enqueue("https://a.com/x", source="test")
        sched.run_worker(mode="until_empty")

        counts = sched.stats()["status_counts"]
        assert counts.get("failed") == 1
        assert sink == []
        sched.close()


class TestPersistence:
    def test_state_survives_reopen(self, tmp_path, sink):
        clock = FakeClock()
        # Scheduler 1: enqueue a bunch of jobs, don't run
        s1 = Scheduler(
            state_file=tmp_path / "jobs.sqlite",
            result_sink=sink.append,
            poll_interval=0.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )
        register_fetcher("test", lambda url, anchors=None, **opts: [url])
        for i in range(3):
            s1.enqueue(f"https://a.com/x{i}", source="test")
        s1.close()

        # Scheduler 2: reopen same file, run
        s2 = Scheduler(
            state_file=tmp_path / "jobs.sqlite",
            result_sink=sink.append,
            poll_interval=0.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )
        # Jobs still pending
        assert s2.stats()["status_counts"].get("pending") == 3
        s2.run_worker(mode="until_empty")
        assert s2.stats()["status_counts"].get("done") == 3
        assert len(sink) == 3
        s2.close()


class TestSink:
    def test_sink_exception_does_not_cause_retry(self, scheduler):
        register_fetcher("test", lambda url, anchors=None, **opts: [url])

        def bad_sink(result):
            raise RuntimeError("sink blew up")

        # Replace the sink post-construction via the private attribute
        # (real consumers would pass a robust sink; this test confirms we
        # don't retry on sink failures.)
        scheduler._result_sink = bad_sink  # type: ignore[assignment]

        scheduler.enqueue("https://a.com/x", source="test")
        scheduler.run_worker(mode="until_empty")

        counts = scheduler.stats()["status_counts"]
        assert counts.get("done") == 1
        assert counts.get("failed", 0) == 0


class TestStop:
    def test_stop_breaks_forever_loop(self, scheduler, clock):
        call_count = {"n": 0}

        def fetcher(url, anchors=None, **opts):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                scheduler.stop()
            return [url]

        register_fetcher("test", fetcher)
        scheduler.enqueue("https://a.com/x1", source="test")
        scheduler.enqueue("https://a.com/x2", source="test")
        scheduler.enqueue("https://a.com/x3", source="test")

        scheduler.run_worker(mode="forever")

        # Stopped after 2 jobs; third stays pending
        counts = scheduler.stats()["status_counts"]
        assert counts.get("done") == 2
        assert counts.get("pending") == 1


class TestStats:
    def test_status_counts_empty(self, scheduler):
        stats = scheduler.stats()
        assert stats["status_counts"] == {}
        assert stats["domains"] == {}

    def test_status_counts_reflect_jobs(self, scheduler):
        register_fetcher("test", lambda url, anchors=None, **opts: [url])
        scheduler.enqueue("https://a.com/x", source="test")
        scheduler.enqueue("https://b.com/x", source="test")
        stats = scheduler.stats()
        assert stats["status_counts"]["pending"] == 2
