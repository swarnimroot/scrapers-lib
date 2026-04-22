# scrapers-lib — Tasks and Roadmap

**Status:** draft &nbsp;·&nbsp; **Last updated:** 2026-04-21 &nbsp;·&nbsp; **Library version:** 0.2.0 (pre-release)

This is the operational roadmap. Unlike PRD and Architecture, this document is **demo-aware** — specific consumer projects drive the order in which sources get built. The roadmap is pruned and rewritten as demos come and go.

---

## Current state

**Last updated:** 2026-04-21

- **Last session:** **Wave 2b Lenovo + HP COMPLETE.** `tier2/hp.py` — plain-httpx fetcher that extracts HP's shop-PDP state from a hidden `<div id="data"><!-- {JSON} --></div>` block and walks `slugInfo.components.pdpCTOConfiguration.configurations` to emit one `ProductSnapshot` per "Recommended Configuration" tile (typically 3) with 11–12 config-picker spec categories per tile, current value first + alternatives joined with `\n`. Verified on Omen Max 16t-ah000 + Pavilion 16z-ag000 (54 unit tests + 1 gated live integration). Known coverage caveat documented in ARCHITECTURE.md §11: the "Tech Specs" section (~20 more categories — Dimensions, Ports, Weight, Warranty) is client-side hydrated behind an aggressive bot gate that rejects even stealth Playwright with homepage warming. HP QuickSpecs PDFs at `h20195.www2.hp.com` are the upgrade path; not built yet. `tier2/lenovo.py` (earlier this wave) remains green — 47 tests + live integration, plain httpx against PSREF's `LoadSpecData` JSON API. Three source-specific recon probes at `scripts/hp/`, three at `scripts/lenovo/`, four at `scripts/dell/`. Wave 2a Dell still green.
- **In progress:** none (pause point).
- **Next:** Wave 2b continues — ASUS / Acer / MSI. Each requires its own reconnaissance per the golden rule in `docs/ADDING_A_SOURCE.md` §2 (three sites in and still zero shared helpers — don't assume anything hoists). §5 decision tree is the starting framework; `scripts/lenovo/probe_psref.py` and `scripts/hp/probe_hp_pdp.py` are the lightest-weight probe templates.
- **Dev env:** `.venv/` with Wave 1 deps + `beautifulsoup4`, `playwright`, `playwright-stealth`, and Chromium installed via `playwright install chromium`.
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

- [x] Create folder structure (`scrapers_lib/core`, `tier1`, `tier2`, `tier3`, `tests/`, `docs/`)
- [x] `pyproject.toml` with pinned dependencies, hatch build backend
- [x] `.env.example` listing Reddit + BestBuy keys (more added as sources land)
- [x] `.gitignore` (`.env`, `.venv`, `__pycache__`, `.cache`, `data/`, `jobs.sqlite`, `.claude/`)
- [x] `LICENSE` (MIT) + `CHANGELOG.md`
- [x] Empty module files in each package (`schemas.py`, `cache.py`, etc.) so imports resolve
- [x] Local `git init`; first commit = "scaffold" (`2dfbe2a`)

## Wave 1 — Core library

Build order within Wave 1 — later items depend on earlier ones:

- [x] `core/logging_config.py` — stdlib logging, per-module loggers
- [x] `core/schemas.py` — Anchor, ProductSnapshot, RawMention (Pydantic v2) + enums
  - [x] Unit tests: schema validation happy path + failure cases
- [x] `core/attribution.py` — regex gate, URL-map gate, deterministic mention-ID helpers
  - [x] Unit tests: primary-only, primary+corroboration, exclusion, ambiguous-match routing
- [x] `core/cache.py` — diskcache wrapper with per-source TTL, URL-default keys
  - [x] Unit tests: cache hit/miss, TTL expiry
- [x] `core/rate_limiter.py` — per-domain token buckets
  - [x] Unit tests: under budget, at budget, budget reset
- [x] `core/robots.py` — robots.txt fetch + cache; per-call `ignore_robots` override
  - [x] Unit tests: allowed path, disallowed path, missing robots.txt, override
- [x] `core/http_client.py` — httpx wrapper with retry/backoff, UA rotation, `Retry-After` respect
  - [x] Unit tests: 429 backoff, 503 backoff, bounded retry count
- [x] `core/playwright_base.py` — stealth settings, persistent browser profile per domain
  - [x] Unit tests for `BrowserProfile` / `_safe_domain` (pure-Python parts). `stealth_context` itself is integration-only and will be exercised in Wave 2a.
- [x] `core/registry.py` — internal fetcher registry keyed by source-name
  - [x] Unit tests: register, lookup, duplicate-name protection
- [x] `core/scheduler.py` — SQLite-backed job queue, worker loop, per-domain budgets, adaptive backoff, callback sink, stats
  - [x] Unit tests: enqueue, dequeue, budget exhaustion, failure retry, state persistence
- [x] Commit per module; tag `v0.1.0` on Wave 1 completion

## Wave 2a — Demo 2 sources: Dell (narrowed scope)

Driver: **Demo 2**. Scope narrowed to `_base` + Dell only so the shared helpers get validated against one real site before five more manufacturers depend on them.

- [x] `tier2/_base.py` — shared parsing helpers: `parse_product_jsonld`, `parse_inline_json`, `parse_spec_table`, `normalize_spec_value`, `fetch_rendered_html` (46 unit tests)
- [x] `core/playwright_base.py` upgraded — integrated `playwright-stealth`, Chrome-145 UA (Wave 1 stealth tripped Akamai)
- [x] `tier2/dell.py` — stealth browser session + `csbapi/unifiedpd/techspecs` endpoint per tile; one `ProductSnapshot` per `data-oc` with ~20 spec categories; tile-bullet fallback on API failure (47 unit tests)
  - [x] Integration test (gated): fetch Alienware Aurora 16X live; validate shape
- [x] Dell row added to `docs/ARCHITECTURE.md` §11
- [x] Reconnaissance methodology doc (`docs/ADDING_A_SOURCE.md`) + Dell recon scripts (`scripts/dell/`) committed — captures why-we-did-it-this-way and the decision tree for adding new manufacturers
- [x] Bump `version` to `0.2.0` in `pyproject.toml` and `scrapers_lib/__init__.py`
- [x] Tag `v0.2.0`

## Wave 2b — remaining Tier 2 manufacturers

Driver: **Demo 2**. Each manufacturer likely uses a different spec-acquisition pattern than Dell (Dell → internal `csbapi` endpoint; Lenovo → PSREF `LoadSpecData` JSON API; HP/ASUS/Acer/MSI to be determined by per-site recon). Don't assume one pattern hoists into `_base` until a second site confirms it.

- [x] `tier2/hp.py` — shop-PDP state-JSON extraction (hidden `<div id="data"><!-- {JSON} --></div>`); per-tile `ProductSnapshot` with 12 config-picker categories; plain httpx (HP doesn't bot-gate httpx but blocks browsers); verified on Omen Max 16t-ah000 + Pavilion 16z-ag000 (54 unit tests + 1 gated live integration). **Known limitation**: "Tech Specs" section (Dimensions/Ports/Weight/Warranty — 20+ more categories) is client-side hydrated behind an aggressive bot gate; HP QuickSpecs PDFs at `h20195.www2.hp.com` are the upgrade path for full coverage.
- [x] `tier2/lenovo.py` — PSREF `LoadSpecData` JSON endpoint, plain httpx (no stealth); verified on Legion Pro 7 16AFR10H + LOQ 15IRX10 (47 unit tests + 1 gated live integration)
- [ ] `tier2/asus.py`
- [ ] `tier2/acer.py`
- [ ] `tier2/msi.py`
- [ ] Per-source coverage rows added to `docs/ARCHITECTURE.md` §11 — [x] Lenovo, [x] HP
- [ ] Hoist any patterns that recur across two or more sites into `tier2/_base.py` (so far Dell's HTML-fragment parsing, Lenovo's nested-JSON flattening, and HP's comment-wrapped-state-JSON extraction all share **zero** helpers — no hoisting yet)
- [ ] Tag `v0.3.0` on Wave 2b completion

## Wave 2c — BestBuy + Amazon

Driver: the need for retailer product + review data. Builds on the stealth browser primitive from Wave 2a.

- [ ] `tier1/bestbuy_api.py` — product data via BestBuy Developer API (no reviews)
  - [ ] Integration test (gated): fetch one product by SKU
- [ ] `tier3/bestbuy.py` — reviews only (URL-driven, Playwright + stealth)
  - [ ] Integration test (gated): fetch reviews for one URL
- [ ] `tier3/amazon.py` — product + reviews (URL-driven, Playwright + stealth)
  - [ ] Integration test (gated): fetch product + reviews for one ASIN URL
- [ ] Windows Task Scheduler setup guide added to `README.md` (for running the worker 24x7)
- [ ] Per-source coverage notes updated
- [ ] Tag `v0.4.0` on Wave 2c completion

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
- [ ] Tag `v0.5.0` on Wave 3 completion

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
