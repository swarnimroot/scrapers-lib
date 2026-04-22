# scrapers-lib — Tasks and Roadmap

**Status:** draft &nbsp;·&nbsp; **Last updated:** 2026-04-22 &nbsp;·&nbsp; **Library version:** 0.4.0 (pre-release)

This is the operational roadmap. Unlike PRD and Architecture, this document is **demo-aware** — specific consumer projects drive the order in which sources get built. The roadmap is pruned and rewritten as demos come and go.

---

## Current state

**Last updated:** 2026-04-22 (session-end wrap)

- **Last session:** **Wave 2c COMPLETE.** Three new fetchers shipped: `tier3/amazon.py` (product + reviews via plain httpx — Amazon's PDP is reachable at the TLS layer, counter to its Tier 3 reputation; 78 unit tests across two ASINs exercising both `#bylineInfo` render variants), `tier1/bestbuy_api.py` (BestBuy Developer API — 55 unit tests against synthetic fixtures matching the documented API schema, live test doubly-gated on `BESTBUY_API_KEY` + `SCRAPERSLIB_LIVE_TESTS=1`), and `tier3/bestbuy.py` (reviews only; uses **curl_cffi with Chrome TLS impersonation on HTTP/1.1** — the combination that bypasses Akamai's HTTP/2 RST-stream gate after a three-step recon escalation proved plain httpx, stealth Playwright, and curl_cffi-on-HTTP/2 all fail; 37 unit tests across two Alienware SKUs). One dependency added: `curl_cffi>=0.7` (free, open-source, drop-in `requests`-like API — same upgrade path documented for HP's coverage gap). **Full suite: 584 passed, 7 skipped** (one live integration per active source — Dell / HP / Lenovo / ASUS / Amazon / BestBuy API / BestBuy reviews).
- **In progress:** none (pause point). User has the Reddit PRAW walkthrough instructions; BestBuy Developer API registration pending (approval ~1 week from submission).
- **Next:** **Wave 3** (Demo 3 gaming radar) — RSS → article → Reddit → YouTube. Four fetchers, each adding one dep (`feedparser`, `trafilatura`, `praw`, `youtube-transcript-api`) — flagged for approval per `CLAUDE.md` before installing. Reddit is the dep where the user's PRAW walkthrough credentials become load-bearing.
- **Dev env:** `.venv/` with Wave 1 deps + `beautifulsoup4` + `playwright` + `playwright-stealth` + `curl_cffi` (new in Wave 2c) and Chromium installed via `playwright install chromium`.
- **Open questions:** none blocking. BestBuy reviews pagination (`/site/reviews/name/<SKU>?page=N`) and Amazon `/product-reviews/<ASIN>/` deep pagination are deferred as future-wave enhancements once a demo needs the long-tail reviews; current PDP-inlined coverage (~5 BestBuy, ~10 Amazon) meets Demo 1 / Demo 2 needs.

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
- [x] `tier2/asus.py` — ROG marketing/spec page at `rog.asus.com/laptops/<line>/<model>/spec/`, SSR'd `<h2>` sections parsed by CSS-module class-prefix matching; one `ProductSnapshot` per URL with **20+ spec categories** including the Dimensions/Ports/Weight axes HP cannot deliver; plain httpx; verified on ROG Strix G16 2025 + ROG Zephyrus G16 2026 (50 unit tests + 1 gated live integration). `shop.asus.com` is DataDome-gated so the fetcher targets the ROG marketing surface which carries no prices.
- [ ] ~~`tier2/acer.py`~~ — **Deferred (post-demo)**. Not required for Demo 2 max-spec comparison; Dell/HP/Lenovo/ASUS cover the four major gaming-laptop manufacturers. Revisit after demo ships if broader coverage becomes necessary.
- [ ] ~~`tier2/msi.py`~~ — **Deferred (post-demo)**, same rationale as Acer.
- [x] Per-source coverage rows added to `docs/ARCHITECTURE.md` §11 — [x] Lenovo, [x] HP, [x] ASUS (Acer/MSI documented as deferred)
- [ ] Hoist any patterns that recur across two or more sites into `tier2/_base.py` (**four** Tier 2 sources in — Dell HTML-fragment parsing + Lenovo nested-JSON API + HP comment-wrapped-state-JSON + ASUS h2-headed DOM sections — and still zero shared helpers; every site so far is bespoke)
- [x] Tag `v0.3.0` on Wave 2b completion (handled as part of ASUS commit; Acer/MSI deferred)

## Wave 2c — BestBuy + Amazon

Driver: the need for retailer product + review data. Recon during this wave proved Amazon's PDP is plain-httpx reachable (surprise vs Tier 3 reputation); BestBuy's PDP required a three-step escalation landing on `curl_cffi` + Chrome impersonation + HTTP/1.1 after plain httpx, stealth Playwright, and curl_cffi-on-HTTP/2 all failed to get past Akamai's HTTP/2 RST-stream gate.

- [x] `tier1/bestbuy_api.py` — product data via BestBuy Developer API (no reviews)
  - [x] Integration test (gated): fetch one product by SKU (doubly gated on `BESTBUY_API_KEY` + `SCRAPERSLIB_LIVE_TESTS=1`)
- [x] `tier3/bestbuy.py` — reviews only (curl_cffi + Chrome impersonation + HTTP/1.1; parses JSON-LD `Product.review[*]`)
  - [x] Integration test (gated): fetch reviews for one URL
- [x] `tier3/amazon.py` — product + reviews (plain httpx; two registered fetchers in one module — `amazon` for ProductSnapshot, `amazon_reviews` for RawMention)
  - [x] Integration test (gated): fetch product + reviews for one ASIN URL
- [x] Windows Task Scheduler setup guide added to `README.md` (for running the worker 24x7)
- [x] Per-source coverage notes updated in `docs/ARCHITECTURE.md` §11
- [x] Reconnaissance scripts + per-site READMEs committed: `scripts/amazon/`, `scripts/bestbuy/`
- [x] Dependency added with user approval: `curl_cffi>=0.7`
- [x] Tag `v0.4.0` on Wave 2c completion

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
