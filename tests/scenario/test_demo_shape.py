"""End-to-end scenario test: real Scheduler + real fetchers.

Individual fetchers are validated by their own integration tests
(``tests/tier*/test_*_integration.py``). The Scheduler is unit-tested
with mocked fetchers. What is NOT otherwise tested anywhere is the
**combination** — the Scheduler dispatching to real fetchers via a
real rate-limited, robots-respecting worker loop, with a real
result_sink collecting heterogeneous output through the same pipeline.
That gap is what this scenario test closes.

**Scope is intentionally Tier 1 only.** The three Tier 1 fetchers
exercised here — RSS / Reddit (unauthenticated JSON) / YouTube
(transcript API) — have no bot-gate to trip and run fast enough that
the Scheduler's orchestration is the only variable. Tier 2 (Dell /
HP / Lenovo / ASUS) and Tier 3 (Amazon / BestBuy reviews) are
**deliberately excluded** because their bot-gated paths flake under
rapid-fire live runs (Akamai throttles harder after several
back-to-back hits from one IP). That flakiness is real-world
behavior, not a Scheduler bug; it is already exercised and tolerated
by each fetcher's own integration test. Mixing them into a scenario
test obscures what the scenario is measuring.

**Runtime target:** under 30 seconds. RSS + Reddit + YouTube combined
are ~10-15 s of network plus Scheduler poll overhead.

**Stricter gate than the live integration tests.** Set
``SCRAPERSLIB_SCENARIO_TESTS=1`` to run. Do not include in the
default live-integration run — these are scenario tests, not source
canaries.

What this test DOES cover:

- Scheduler dispatches to registered fetchers by source name.
- Real fetchers' output flows through the worker loop into a
  user-supplied result_sink as ``RawMention`` instances.
- Discovery mode (``anchors=None``) works end-to-end through the
  Scheduler (the default for Wave 3 Tier 1 fetchers).
- RateLimiter + RobotsChecker don't block legitimate traffic.
- Per-domain stats increment correctly on success.
- ``run_worker(mode="until_empty")`` terminates when all jobs drain.
- State persistence: rerunning on a drained state is a no-op.

What this test does NOT cover (by design):

- Attribution via URL-map (covered by Tier 2/3 integration tests).
- Domain-level backoff after consecutive failures (covered by
  ``tests/core/test_scheduler.py`` with mocked failing fetchers).
- Multi-day scheduling / long-running worker behavior.
- Playwright / curl_cffi bot-gate bypass primitives.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib import (
    RawMention,
    Scheduler,
    __version__,
)
from scrapers_lib.core.rate_limiter import RateLimiter
from scrapers_lib.core.robots import RobotsChecker

# Side-effect imports: each fetcher module registers itself on import.
from scrapers_lib.tier1 import reddit, rss, youtube  # noqa: F401

SCENARIO = bool(os.environ.get("SCRAPERSLIB_SCENARIO_TESTS"))

# URLs intentionally mirror what each fetcher's own integration test uses —
# if those canaries go stale, so does this, and the fix is the same place.
RSS_URL = "https://feeds.ign.com/ign/games-all"
REDDIT_INPUT = "r/Games"  # shorthand accepted by fetch_reddit_listing
YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.skipif(
    not SCENARIO,
    reason="scenario tests disabled; set SCRAPERSLIB_SCENARIO_TESTS=1",
)
class TestSchedulerEndToEndWithTier1:
    """Scheduler drives three real Tier 1 fetchers through one worker loop."""

    def test_end_to_end_drain_with_discovery_mode_fetchers(self, tmp_path):
        """Three Tier 1 jobs enqueued; worker drains; every job lands cleanly."""
        collected: list = []

        def sink(results):
            collected.extend(results)

        rate_limiter = RateLimiter(default_rps=2.0, default_burst=2)
        robots = RobotsChecker(
            user_agent=f"scrapers-lib-scenario/{__version__}",
        )

        with Scheduler(
            state_file=str(tmp_path / "state.db"),
            result_sink=sink,
            rate_limiter=rate_limiter,
            robots=robots,
            poll_interval=0.5,
            default_max_attempts=1,  # fail fast in a scenario test
        ) as sched:
            sched.enqueue(
                RSS_URL, source="rss", anchors=None, source_slug="ign"
            )
            sched.enqueue(
                REDDIT_INPUT, source="reddit", anchors=None, limit=10
            )
            sched.enqueue(
                YOUTUBE_URL,
                source="youtube",
                anchors=None,
                chunk_seconds=60.0,
            )

            sched.run_worker(mode="until_empty")
            stats = sched.stats()

        # ---------- All three jobs succeeded ----------
        done = stats["status_counts"].get("done", 0)
        failed = stats["status_counts"].get("failed", 0)
        pending = stats["status_counts"].get("pending", 0)
        assert done == 3, (
            f"expected 3 done jobs; got done={done} failed={failed} "
            f"pending={pending}. Inspect stats={stats}"
        )
        assert failed == 0, f"unexpected failures: {failed} (stats={stats})"

        # ---------- Result sink received mentions from all three sources ----------
        mentions = [x for x in collected if isinstance(x, RawMention)]
        assert len(mentions) >= 10, (
            f"expected >=10 RawMentions across rss/reddit/youtube; "
            f"got {len(mentions)}"
        )

        mention_sources = {m.source for m in mentions}
        # RSS's ``source`` field is the caller-supplied ``source_slug``
        # (``"ign"``), not ``"rss"`` — that's how the library
        # distinguishes IGN's feed from e.g. Polygon's.
        assert "ign" in mention_sources, (
            f"no RSS mentions (source='ign'); got sources={mention_sources}"
        )
        assert "reddit" in mention_sources, (
            f"no Reddit mentions; got sources={mention_sources}"
        )
        assert "youtube" in mention_sources, (
            f"no YouTube mentions; got sources={mention_sources}"
        )

        # ---------- All mentions are discovery-mode (attribution=None) ----------
        # All three jobs were enqueued with anchors=None; every resulting
        # mention must have attribution=None. This validates that Wave 3's
        # Optional widening of RawMention.attribution flows end-to-end.
        assert all(m.attribution is None for m in mentions), (
            "at least one mention has non-None attribution despite "
            "anchors=None enqueue — discovery mode broken end-to-end"
        )

        # ---------- Per-domain stats increment on success ----------
        success_counts = {
            domain: state["total_successes"]
            for domain, state in stats["domains"].items()
        }
        # Each of the three domains got exactly one successful fetch.
        assert all(n == 1 for n in success_counts.values()), (
            f"per-domain success totals not all 1: {success_counts}"
        )

        # ---------- Domain backoff never kicked in ----------
        for domain, state in stats["domains"].items():
            assert state["consecutive_failures"] == 0, (
                f"unexpected consecutive failures at {domain}: "
                f"{state['consecutive_failures']}"
            )
            assert state["backoff_until"] is None, (
                f"domain {domain} is under backoff after a clean run"
            )

    def test_rerun_worker_on_drained_state_is_noop(self, tmp_path):
        """Scheduler's SQLite state persists across worker invocations.

        Enqueue one job, drain, then re-run ``until_empty`` on the same
        state file. The second run should be a no-op — no new jobs, no
        new results. Verifies the state serialization contract isn't
        accidentally re-running already-done jobs.
        """
        collected: list = []

        def sink(results):
            collected.extend(results)

        rate_limiter = RateLimiter(default_rps=2.0, default_burst=2)
        robots = RobotsChecker(
            user_agent=f"scrapers-lib-scenario/{__version__}",
        )

        kwargs = dict(
            state_file=str(tmp_path / "state.db"),
            result_sink=sink,
            rate_limiter=rate_limiter,
            robots=robots,
            poll_interval=0.5,
            default_max_attempts=1,
        )

        # First run — enqueue and drain
        with Scheduler(**kwargs) as sched:
            sched.enqueue(RSS_URL, source="rss", anchors=None, source_slug="ign")
            sched.run_worker(mode="until_empty")

        first_run_count = len(collected)
        assert first_run_count > 0, "first run collected nothing"
        collected.clear()

        # Second run — same state file, no new enqueues, drain again
        with Scheduler(**kwargs) as sched:
            sched.run_worker(mode="until_empty")
            stats = sched.stats()

        assert collected == [], (
            f"second run re-processed jobs and emitted {len(collected)} "
            f"results; state persistence is broken"
        )
        assert stats["status_counts"].get("done", 0) == 1
