# scrapers-lib — Tasks and Roadmap

**Status:** draft &nbsp;·&nbsp; **Last updated:** 2026-04-22 &nbsp;·&nbsp; **Library version:** 0.5.0 (pre-release)

This is the operational roadmap. Unlike PRD and Architecture, this document is **demo-aware** — specific consumer projects drive the order in which sources get built. The roadmap is pruned and rewritten as demos come and go.

---

## Current state

**Last updated:** 2026-04-22 (session-end wrap)

- **Last session:** **Wave 3 COMPLETE.** Four new Tier 1 fetchers shipped: `tier1/rss.py` (feedparser, dual-mode discovery/anchor-driven — 41 unit tests + 2 gated live against IGN), `tier1/article.py` (trafilatura with `with_metadata=True`, partial-success on paywalls — 38 unit tests + 2 gated live against IGN/Polygon), `tier1/reddit.py` (**unauthenticated** `.json` endpoints — PRAW OAuth is closed per Reddit's Nov-2025 policy, empirically confirmed by a rejected formal application; two registered fetchers: `reddit` listings + `reddit_comments` post-plus-tree bundles — 53 unit tests + 3 gated live against r/Games), `tier1/youtube.py` (`youtube-transcript-api`, 60s default time-windowed chunking with `?t=<s>s` deep-linked `source_url` — 46 unit tests + 2 gated live). **Two library-level additions**: `RawMention.attribution` widened to `Attribution | None` (unlocks discovery mode: pass `anchors=None` → emit everything unfiltered, downstream consumer filters), and `attribute_regex_all(text, anchors) -> list[Attribution]` (multi-anchor matching helper — "Microsoft buys Activision" article fans out to both Microsoft and Activision anchors instead of being dropped on ambiguity). `praw` dropped from `pyproject.toml` since OAuth path is closed. 12-site RSS feed catalog discovered via `scripts/rss/probe_feeds.py` + documented in `scripts/rss/README.md` (IGN / GameSpot / Polygon / PCGamer / Kotaku / Eurogamer / GameInformer / GamesIndustry / GameDeveloper / RockPaperShotgun / VG247 / TheGamer) plus VentureBeat's mixed-content site-wide feed per user decision to let non-gaming content flow through. **Full suite: 762 passed, 16 skipped** (one gated live integration per active fetcher across all three tiers).
- **In progress:** none (pause point).
- **Next:** **Wave 4** (v1.0 readiness) — review public APIs for stability, flip doc status headers to "stable", remove `draft` / *(subject to revision)* qualifications, ensure integration tests cover every fetcher, final per-source coverage table, tag `v1.0.0`. After Wave 4: **Wave 2d** — BestBuy review pagination (`/site/reviews/name/<SKU>?page=N`) that unlocks `published_at` and long-tail reviews; scheduled as the first post-v1.0.0 additive feature (tag `v1.1.0`). Amazon `/product-reviews/<ASIN>/` deep pagination remains out of reach without credentials (sign-in wall); accept the PDP-inlined top-10 as the reachable subset.
- **Dev env:** `.venv/` with Wave 1 deps + `beautifulsoup4` + `playwright` + `playwright-stealth` + `curl_cffi` + `feedparser` + `trafilatura` + `youtube-transcript-api` (no `praw`). Chromium installed via `playwright install chromium`.
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

## Wave 2d — BestBuy reviews: long-tail pagination *(scheduled post-v1.0.0)*

**Scheduled after Wave 4.** This wave extends `tier3/bestbuy.py` from the
inline PDP review cap (~5 per fetch, no `datePublished`) to full
pagination of `bestbuy.com/site/reviews/name/<SKU>?page=N`. The
fetched page carries `datePublished` per review — unlocks time-series
sentiment on BestBuy, which v0.4.0 cannot do. Same `curl_cffi` +
Chrome impersonation + HTTP/1.1 primitive that `tier3/bestbuy.py`
already uses is presumptively sufficient (same host, same Akamai
deployment); needs a probe before build.

- [ ] Recon probe: confirm `/site/reviews/name/<SKU>` reachable via curl_cffi + HTTP/1.1 + homepage warming; inspect review-card DOM shape on page 1 + page 2
- [ ] Add a paginated-review fetcher (new function, does not replace the fast inline-5 path) — caps configurable via `max_pages` / `per_page` kwargs to respect patient-pacing
- [ ] Populate `published_at` on each RawMention from the page
- [ ] Unit tests + fixtures for page 1 + page 2 on two unrelated SKUs
- [ ] `docs/ARCHITECTURE.md` §11 coverage-row update (BestBuy reviews with full-tail + dates)
- [ ] CHANGELOG bullet; tag `v1.1.0` (additive post-1.0 feature)

## Wave 3 — Demo 3 sources (gaming radar)

Driver: **Demo 3**. Order — RSS first (simplest), then article body, then Reddit, then YouTube. Dual-mode (discovery / anchor-driven) was added to the schema in this wave to support both "what's popular right now, no filter" and "what's being said about X" use cases.

- [x] `tier1/rss.py` — feedparser-based; emits RawMentions from feed entries. Dual-mode via `anchors=None`-or-list. 41 unit + 2 gated live tests.
  - [x] Integration test (gated): fetch IGN's games feed, verify discovery + anchor modes
  - [x] Feed-discovery tooling: `scripts/rss/probe_feeds.py` + Demo 3 catalog of 12 gaming sites (+ VentureBeat mixed) in `scripts/rss/README.md`
- [x] `tier1/article.py` — trafilatura-based; follow-up body fetch when RSS summary is insufficient. Partial-success on paywalls (returns empty list, never raises on quality). 38 unit + 2 gated live tests.
  - [x] Integration test (gated): fetch body from IGN + Polygon URLs (different CMS shapes)
- [x] `tier1/reddit.py` — **unauthenticated JSON endpoints** (`.json` suffix) — PRAW OAuth self-service closed by Reddit's Nov-2025 policy, formal application rejected. Two registered fetchers (listing + comments). Public signature stays PRAW-compatible. 53 unit + 3 gated live tests.
  - [x] Integration test (gated): r/Games listing + one post's comments bundle + anchor-mode sanity check
- [x] `tier1/youtube.py` — `youtube-transcript-api`; emits RawMentions from time-windowed transcript chunks (60s default). Deep-linked `source_url` with `?t=<s>s`. Translates library exceptions (no-transcript/age-gated → empty list; RequestBlocked/IpBlocked → BlockedError). 46 unit + 2 gated live tests.
  - [x] Integration test (gated): Rick Astley stable canary + anchor-mode match
- [x] **Library-level schema change**: `RawMention.attribution: Attribution | None` (additive; existing consumers unaffected).
- [x] **New helper**: `attribute_regex_all` (multi-anchor match) + `article_mention_id` ID helper.
- [x] **Dep removed**: `praw` (OAuth path closed).
- [x] Per-source coverage rows updated in `docs/ARCHITECTURE.md` §11.
- [x] Tag `v0.5.0` on Wave 3 completion

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
