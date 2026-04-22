# scrapers-lib — Tasks and Roadmap

**Status:** draft &nbsp;·&nbsp; **Last updated:** 2026-04-21 &nbsp;·&nbsp; **Library version:** 0.1.0 (pre-release)

This is the operational roadmap. Unlike PRD and Architecture, this document is **demo-aware** — specific consumer projects drive the order in which sources get built. The roadmap is pruned and rewritten as demos come and go.

---

## Current state

**Last updated:** 2026-04-21

- **Last session:** Wave 1 partial — `core/schemas.py` and `core/attribution.py` implemented with 55 passing unit tests (commits `2dfbe2a` scaffold, `798ef6d` core schemas + attribution). Top-level re-exports in place at `scrapers_lib`.
- **In progress:** Wave 1 continues.
- **Next:** `core/logging_config.py`, then `core/cache.py`, `core/rate_limiter.py`, `core/http_client.py`, `core/robots.py`, `core/playwright_base.py`, `core/registry.py`, `core/scheduler.py`.
- **Dev env:** `.venv/` in place with `pydantic>=2.0` and `pytest>=8.0`; extend with additional deps as later modules need them (`httpx`, `diskcache`, `playwright`, etc.).
- **Open questions:** none blocking.

### How to resume in a new session

Say "Resume scrapers-lib" (or similar). Claude will read memory files (auto-loaded), this Current state block, and `git log --oneline -10`, then summarize and propose the next step before touching anything.

### End-of-session ritual

Say "wrap this session" (or similar). Claude will commit any in-flight work (or mark it WIP), update this Current state block, check off completed items below, and add a line to `CHANGELOG.md` `[Unreleased]` if anything user-visible changed.

---

## Current demo drivers

- **Demo 1 — Alienware Competitive Response Drafter.** Standalone, already built. **Not a constraint on the library.** Will port onto scrapers-lib later if and when the user chooses. Not scheduled.
- **Demo 2 — Hot Response (manufacturer spec comparisons).** Scrapes Dell / HP / Lenovo / ASUS / Acer / MSI pages for maximum spec detail per product. Driver for Wave 2a.
- **Demo 3 — Gaming news radar.** Aggregates ~20 gaming news / reviewer sites + Reddit gaming subs for trend and sentiment. Driver for Wave 3.

---

## Wave 0 — Scaffold

- [ ] Create folder structure (`scrapers_lib/core`, `tier1`, `tier2`, `tier3`, `tests/`, `docs/`)
- [ ] `pyproject.toml` with pinned dependencies, hatch build backend
- [ ] `.env.example` listing Reddit + BestBuy keys (more added as sources land)
- [ ] `.gitignore` (`.env`, `.venv`, `__pycache__`, `.cache`, `data/`, `jobs.sqlite`)
- [ ] `LICENSE` (MIT)
- [ ] Empty module files in each package (`schemas.py`, `cache.py`, etc.) so imports resolve
- [ ] Local `git init`; first commit = "scaffold"

## Wave 1 — Core library

Build order within Wave 1 — later items depend on earlier ones:

- [ ] `core/logging_config.py` — stdlib logging, per-module loggers
- [x] `core/schemas.py` — Anchor, ProductSnapshot, RawMention (Pydantic v2) + enums
  - [x] Unit tests: schema validation happy path + failure cases
- [x] `core/attribution.py` — regex gate, URL-map gate, deterministic mention-ID helpers
  - [x] Unit tests: primary-only, primary+corroboration, exclusion, ambiguous-match routing
- [ ] `core/cache.py` — diskcache wrapper with per-source TTL, URL-default keys
  - [ ] Unit tests: cache hit/miss, TTL expiry
- [ ] `core/rate_limiter.py` — per-domain token buckets
  - [ ] Unit tests: under budget, at budget, budget reset
- [ ] `core/robots.py` — robots.txt fetch + cache; per-call `ignore_robots` override
  - [ ] Unit tests: allowed path, disallowed path, missing robots.txt, override
- [ ] `core/http_client.py` — httpx wrapper with retry/backoff, UA rotation, `Retry-After` respect
  - [ ] Unit tests: 429 backoff, 503 backoff, bounded retry count
- [ ] `core/playwright_base.py` — stealth settings, persistent browser profile per domain
  - [ ] No unit tests (integration-only; gated)
- [ ] `core/registry.py` — internal fetcher registry keyed by source-name
  - [ ] Unit tests: register, lookup, duplicate-name protection
- [ ] `core/scheduler.py` — SQLite-backed job queue, worker loop, per-domain budgets, adaptive backoff, callback sink, stats
  - [ ] Unit tests: enqueue, dequeue, budget exhaustion, failure retry, state persistence
- [ ] Commit per module; tag `v0.1.0` on Wave 1 completion

## Wave 2a — Demo 2 sources (manufacturer spec scraping)

Driver: **Demo 2**. Order — Dell first (BTO configurator is hardest; forces the base right), others follow.

- [ ] `tier2/_base.py` — shared spec-table extraction helpers
- [ ] `tier2/dell.py` — product page + BTO variants; emits multiple ProductSnapshots for configurable products
  - [ ] Integration test (gated): fetch one Dell product page; validate ProductSnapshot shape
- [ ] `tier2/hp.py`
- [ ] `tier2/lenovo.py`
- [ ] `tier2/asus.py`
- [ ] `tier2/acer.py`
- [ ] `tier2/msi.py`
- [ ] Per-source coverage notes added to `docs/ARCHITECTURE.md` §11
- [ ] Tag `v0.2.0` on Wave 2a completion

## Wave 2b — BestBuy + Amazon

Driver: the need for retailer product + review data. Requires Playwright stealth from Wave 1.

- [ ] `tier1/bestbuy_api.py` — product data via BestBuy Developer API (no reviews)
  - [ ] Integration test (gated): fetch one product by SKU
- [ ] `tier3/bestbuy.py` — reviews only (URL-driven, Playwright + stealth)
  - [ ] Integration test (gated): fetch reviews for one URL
- [ ] `tier3/amazon.py` — product + reviews (URL-driven, Playwright + stealth)
  - [ ] Integration test (gated): fetch product + reviews for one ASIN URL
- [ ] Windows Task Scheduler setup guide added to `README.md` (for running the worker 24x7)
- [ ] Per-source coverage notes updated
- [ ] Tag `v0.3.0` on Wave 2b completion

## Wave 3 — Demo 3 sources (gaming radar)

Driver: **Demo 3**. Order — RSS first (simplest), then article body, then Reddit, then YouTube (optional).

- [ ] `tier1/rss.py` — feedparser-based; emits RawMentions from feed entries
  - [ ] Integration test (gated): fetch one known feed
- [ ] `tier1/article.py` — trafilatura-based; follow-up body fetch when RSS summary is insufficient
  - [ ] Integration test (gated): fetch body from one known article URL
- [ ] `tier1/reddit.py` — PRAW-based; emits RawMentions from posts + comment trees with per-comment attribution
  - [ ] Integration test (gated): search one subreddit for a known topic
- [ ] `tier1/youtube.py` — youtube-transcript-api; emits RawMentions from transcript chunks
  - [ ] Integration test (gated): fetch one known video's transcript
- [ ] Per-source coverage notes updated
- [ ] Tag `v0.4.0` on Wave 3 completion

## Wave 4 — v1.0 readiness

- [ ] Review all public APIs for stability; document any still-unstable areas
- [ ] Flip all doc status headers to "stable"
- [ ] Remove remaining `draft` or *(subject to revision)* qualifications
- [ ] Ensure integration tests cover every fetcher
- [ ] Final per-source coverage table
- [ ] Tag `v1.0.0`

## Deferred (not blocking any current demo)

- Consumer project scaffolds (`demo-2-hot-response/`, `demo-3-gaming-radar/`) — created when Wave 2a and Wave 3 are ready to be consumed.
- Demo 1 port onto scrapers-lib — user discretion, not scheduled.
- Additional Tier 1 sources: Walmart affiliate API, YouTube Data API (channel monitoring).
- Additional Tier 2 sources: forums, more manufacturers.
- Additional Tier 3 sources: Newegg, Target, Costco.
- Plugin registration API (fetcher signature is already plugin-compatible).
- Spec-vocabulary normalization helpers.
- PyPI publication.
- Distributed Scheduler coordination across multiple workers.
