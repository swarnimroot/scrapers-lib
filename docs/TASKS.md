# scrapers-lib — Tasks and Roadmap

**Status:** stable &nbsp;·&nbsp; **Last updated:** 2026-05-05 &nbsp;·&nbsp; **Library version:** 1.1.0

This is the operational roadmap. Unlike PRD and Architecture, this document is **demo-aware** — specific consumer projects drive the order in which sources get built. The roadmap is pruned and rewritten as demos come and go.

---

## Current state

**Last updated:** 2026-05-05 (Wave 2e rescoped + Wave 2f added; commitment date for Wave 2e)

- **Latest tag:** **v1.1.0** (commit 22c7e85). Post-tag polish landed at cf6e58f: `docs/CONSUMER_GUIDE.md` (recipe-oriented guide for consumer-project authors) + `tests/scenario/test_demo_shape.py` (gated scenario test for Scheduler orchestration). No API changes in the polish commit; no version bump.
- **Wave history (all shipped):** Wave 0 (scaffold) → Wave 1 (core, v0.1.0) → Wave 2a (Dell, v0.2.0) → Wave 2b (HP/Lenovo/ASUS, v0.3.0) → Wave 2c (BestBuy + Amazon, v0.4.0) → Wave 3 (RSS/article/Reddit/YouTube, v0.5.0) → **Wave 4 (v1.0 readiness, v1.0.0)** → Wave 2d (BestBuy reviews pagination, v1.1.0).
- **In progress:** none (pause point).
- **Next direction (committed 2026-05-05):** **Wave 2e — Tier 2 expansion (HP fix + ASUS www + Lenovo URL acceptance recon)**. Wave 2f follows with Acer + MSI greenfield fetchers. Driver: Demo 2's consumer-side data-model target — the **`Competitor Columns` 83-row spec schema** (CPU / GPU / Memory / Display / Battery / I/O / Thermals / Design) — needs ~80–90% raw coverage across all six manufacturer brands so a separate user-owned downstream project can clean and present the data. Library remains **frozen at v1.x** public API; Wave 2e/2f changes are additive (new fetcher modules + behind-fetcher acquisition rewrite). Pilot 1 brainstorming (pivoted Demo 1 per `project_demo1_pulse_check`) and BestBuy Developer API activation (per `project_bestbuy_api_dormant`) remain on hold.
- **Test state:** unit 809 passed / 19 skipped (2 scenario tests gated by `SCRAPERSLIB_SCENARIO_TESTS=1` + 16 live integration tests gated by `SCRAPERSLIB_LIVE_TESTS=1` + 1 BestBuy API test skipped pending credential). Full live run most recently 825 passed / 1 skipped.
- **Dev env:** `.venv/` with all library deps (pydantic, httpx, curl_cffi, beautifulsoup4, playwright, playwright-stealth, feedparser, trafilatura, youtube-transcript-api, diskcache, python-dotenv). Chromium installed via `playwright install chromium`.
- **Open questions:** none blocking library work.

### How to resume in a new session

Say "Resume scrapers-lib" (or similar). Claude will read memory files (auto-loaded), this Current state block, and `git log --oneline -10`, then summarize and propose the next step before touching anything.

### End-of-session ritual

Say "wrap this session" (or similar). Claude will commit any in-flight work (or mark it WIP), update this Current state block, check off completed items below, and add a line to `CHANGELOG.md` `[Unreleased]` if anything user-visible changed.

---

## Current consumer drivers

- **Pilot 1 — product sentiment & reviews (pivoted 2026-04-22 from Demo 1).** PC-manufacturer-POV tool that reads consumer sentiment across the library's sources to inform product / pricing / positioning / warranty decisions. Currently in brainstorm phase; scope not locked. Uses hybrid LLM routing (local for classification volume; Anthropic for synthesis quality). See memory `project_demo1_pulse_check.md` for the full framing. **Note:** the pre-scrapers-lib standalone "Pulse Check" 9-script pipeline was the previous attempt; treated as data-shape witness only, not a template (see memory `project_demo1_not_a_scraping_reference.md`).
- **Demo 2 — Hot Response (manufacturer spec comparisons).** Scrapes Dell / HP / Lenovo / ASUS / Acer / MSI manufacturer pages for maximum spec detail per product, targeting the consumer-side **`Competitor Columns` 83-row spec schema** (CPU / GPU / Memory / Display / Battery / I/O / Thermals / Design). Drove Wave 2a/2b; Wave 2e + 2f close remaining coverage gaps. Today's per-brand raw coverage estimate: Lenovo PSREF ~95%, ASUS ROG ~85–90%, Dell ~75–80%, HP ~37% (blocked on browser bot gate — Wave 2e fix), ASUS non-ROG / Acer / MSI 0% (fetchers not yet built). Wave 2e/2f bring all six to ~80–90%+. Library scope ends at raw acquisition; downstream parsing / normalization / spreadsheet population is a separate user-owned project. Status / Segment / Year / Sub Brand columns are editorial (not on PDPs) and remain manual.
- **Demo 3 — Gaming news radar.** Aggregates ~20 gaming news / reviewer sites + Reddit gaming subs for trend and sentiment. Drove Wave 3. Library side is ready; consumer not started.

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

Driver: **Demo 2**. Scope narrowed to `base` + Dell only so the shared helpers get validated against one real site before five more manufacturers depend on them.

- [x] `tier2/base.py` — shared parsing helpers: `parse_product_jsonld`, `parse_inline_json`, `parse_spec_table`, `normalize_spec_value`, `fetch_rendered_html` (46 unit tests)
- [x] `core/playwright_base.py` upgraded — integrated `playwright-stealth`, Chrome-145 UA (Wave 1 stealth tripped Akamai)
- [x] `tier2/dell.py` — stealth browser session + `csbapi/unifiedpd/techspecs` endpoint per tile; one `ProductSnapshot` per `data-oc` with ~20 spec categories; tile-bullet fallback on API failure (47 unit tests)
  - [x] Integration test (gated): fetch Alienware Aurora 16X live; validate shape
- [x] Dell row added to `docs/ARCHITECTURE.md` §11
- [x] Reconnaissance methodology doc (`docs/ADDING_A_SOURCE.md`) + Dell recon scripts (`scripts/dell/`) committed — captures why-we-did-it-this-way and the decision tree for adding new manufacturers
- [x] Bump `version` to `0.2.0` in `pyproject.toml` and `scrapers_lib/__init__.py`
- [x] Tag `v0.2.0`

## Wave 2b — remaining Tier 2 manufacturers

Driver: **Demo 2**. Each manufacturer likely uses a different spec-acquisition pattern than Dell (Dell → internal `csbapi` endpoint; Lenovo → PSREF `LoadSpecData` JSON API; HP/ASUS/Acer/MSI to be determined by per-site recon). Don't assume one pattern hoists into `base` until a second site confirms it.

- [x] `tier2/hp.py` — shop-PDP state-JSON extraction (hidden `<div id="data"><!-- {JSON} --></div>`); per-tile `ProductSnapshot` with 12 config-picker categories; plain httpx (HP doesn't bot-gate httpx but blocks browsers); verified on Omen Max 16t-ah000 + Pavilion 16z-ag000 (54 unit tests + 1 gated live integration). **Known limitation**: "Tech Specs" section (Dimensions/Ports/Weight/Warranty — 20+ more categories) is client-side hydrated behind an aggressive bot gate; HP QuickSpecs PDFs at `h20195.www2.hp.com` are the upgrade path for full coverage.
- [x] `tier2/lenovo.py` — PSREF `LoadSpecData` JSON endpoint, plain httpx (no stealth); verified on Legion Pro 7 16AFR10H + LOQ 15IRX10 (47 unit tests + 1 gated live integration)
- [x] `tier2/asus.py` — ROG marketing/spec page at `rog.asus.com/laptops/<line>/<model>/spec/`, SSR'd `<h2>` sections parsed by CSS-module class-prefix matching; one `ProductSnapshot` per URL with **20+ spec categories** including the Dimensions/Ports/Weight axes HP cannot deliver; plain httpx; verified on ROG Strix G16 2025 + ROG Zephyrus G16 2026 (50 unit tests + 1 gated live integration). `shop.asus.com` is DataDome-gated so the fetcher targets the ROG marketing surface which carries no prices.
- [ ] ~~`tier2/acer.py`~~ — **Deferred (post-demo)**. Not required for Demo 2 max-spec comparison; Dell/HP/Lenovo/ASUS cover the four major gaming-laptop manufacturers. Revisit after demo ships if broader coverage becomes necessary.
- [ ] ~~`tier2/msi.py`~~ — **Deferred (post-demo)**, same rationale as Acer.
- [x] Per-source coverage rows added to `docs/ARCHITECTURE.md` §11 — [x] Lenovo, [x] HP, [x] ASUS (Acer/MSI documented as deferred)
- [x] ~~Hoist any patterns that recur across two or more sites into `tier2/base.py`~~ — **closed as intentional non-hoist.** Four Tier 2 sources in (Dell HTML-fragment parsing + Lenovo nested-JSON API + HP comment-wrapped-state-JSON + ASUS h2-headed DOM sections); every site's acquisition pattern is bespoke. No recurring shape found to hoist. `tier2/base.py` remains the shared helper module but its contents (jsonld + inline-json + spec-table + rendered-html) date from Wave 2a and none of the Wave 2b fetchers needed to extend it. Decision: leave as-is; revisit only if a fifth Tier 2 source repeats an existing site's pattern.
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

## Wave 2d — BestBuy reviews: long-tail pagination *(shipped v1.1.0, 2026-04-22)*

**Closed 2026-04-22 at v1.1.0.** Extended `tier3/bestbuy.py` from the
inline PDP review cap (~5 per fetch, no `datePublished`) to full
pagination of `bestbuy.com/site/reviews/name/<SKU>?page=N` via a new
`paginate=True` kwarg on the existing `fetch_bestbuy_reviews`. Same
`curl_cffi` + Chrome impersonation + HTTP/1.1 primitive already used
by the PDP path works on the reviews-surface. **Wave 2d recon
revision:** dates live in per-review `<time class="submission-date"
title="...">` DOM elements, NOT in the JSON-LD — the pre-wave
assumption in ARCHITECTURE.md §11 was partially wrong.

- [x] Recon probe `scripts/bestbuy/probe_reviews_pagination.py`: confirmed `/site/reviews/name/<SKU>` reachable via curl_cffi + HTTP/1.1 + homepage warming; 20 reviews per page in `<li class="review-item">` containers; 3 pages captured as fixtures from SKU 6628371 (Alienware Area-51)
- [x] Extended `fetch_bestbuy_reviews` with `paginate: bool = False`, `max_pages: int | None = None`, `page_delay_seconds: float = 3.0` kwargs; default (paginate=False) preserves the v1.0 PDP-inline behavior verbatim
- [x] New public pure-parse `parse_bestbuy_reviews_page` for one paginated page
- [x] Populates `published_at` (UTC-aware from the `<time title>` attr), `raw.verified_purchase`, `raw.helpful_count`, `raw.ownership_duration`
- [x] 47 new unit tests (parse + date parser + helpful-count + verified-purchase + ownership-duration + orchestration via mocked `_iter_reviews_pages` + pagination termination on empty page and missing rel=next); 2 gated live integration tests (default PDP path unchanged; paginate mode verifies ≥10 reviews + all dated across 2 real pages)
- [x] `docs/ARCHITECTURE.md` §11 coverage-row updated (BestBuy reviews with paginate mode + dates + helpful_count + verified_purchase + ownership_duration)
- [x] CHANGELOG v1.1.0 entry; `_version.py` bumped 1.0.0 → 1.1.0; tag `v1.1.0`

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

## Wave 4 — v1.0 readiness *(shipped v1.0.0, 2026-04-22)*

**Closed 2026-04-22 at v1.0.0** (commit 49a1318). Public API frozen.
Pure stability sweep — no new fetchers. See `CHANGELOG.md` v1.0.0
entry for full details.

- [x] Reviewed all public APIs for stability; breaking-change candidates surfaced for user approval before touching (per session-held findings doc)
- [x] Flipped all doc status headers (README / PRD / ARCHITECTURE / TASKS) from "draft" to "stable"
- [x] Removed `draft` callouts + *(subject to revision)* qualifications
- [x] Verified every registered fetcher has a gated live integration test (1 per fetcher across all three tiers)
- [x] Final per-source coverage table populated at ARCHITECTURE.md §11 (13 registered fetchers)
- [x] Tag `v1.0.0` (annotated, 49a1318)

**Additional breaking changes shipped in the same commit** (all flagged + approved):
- [x] `scrapers_lib.tier2._base` renamed to `scrapers_lib.tier2.base` — the module was the documented Tier-2 extension surface but underscore-prefix contradicted that; renamed at the v1.0 boundary so the underscore doesn't get frozen into the public API
- [x] `scrapers_lib/tier2/acer.py` and `msi.py` removed (both were 1-line empty scaffolds with stale docstrings; corresponding entries removed from `cache.DEFAULT_TTLS`)
- [x] Library version single-sourced from new `scrapers_lib/_version.py`; `pyproject.toml` reads via hatchling dynamic version; 5 User-Agent call sites derive their version suffix via f-string
- [x] `pyproject.toml` `Development Status` classifier flipped `2 - Pre-Alpha` → `5 - Production/Stable`
- [x] README drive-by fixes: broken `rss.fetch_feed()` Quickstart corrected to `fetch_rss_feed`; stale Reddit PRAW credentials row rewritten for unauthenticated posture
- [x] Added README "Public API" section between "Repository layout" and "Documentation"

## Post-v1.1.0 polish *(commit cf6e58f, 2026-04-22; no version bump)*

Non-versioned, non-tagged commit preparing the library for consumer-project use. No API changes.

- [x] `docs/CONSUMER_GUIDE.md` — recipe-oriented guide for consumer authors: anchor authoring, SQLite sink pattern, Scheduler wiring, monitoring, error handling, refresh cadences, per-source data-shape quick reference, FAQ
- [x] `tests/scenario/test_demo_shape.py` — end-to-end scenario test gated by `SCRAPERSLIB_SCENARIO_TESTS=1`; validates Scheduler orchestration across real Tier 1 fetchers (rss / reddit / youtube). Tier 2/3 intentionally excluded from scenario scope (their Akamai gates flake under back-to-back hits; isolated integration tests cover them instead)
- [x] README Documentation section updated to list CONSUMER_GUIDE.md as the "start here" doc for consumer authors

## Wave 2e — Tier 2 expansion: HP fix + ASUS www + Lenovo URL acceptance

Driver: closing the highest-leverage Tier 2 manufacturer-coverage gaps so the library can fill the **`Competitor Columns` 83-row spec schema** for Demo 2 at ~80–90% raw coverage per brand. **Rescoped 2026-05-05** from the prior "HP + ASUS www + Acer + MSI" plan — Acer + MSI moved to Wave 2f because they're both greenfield and gate the wave on recon. Wave 2e is now a focused two-fetcher wave with one small recon sub-task.

Recommended order: **HP fix → ASUS www → Lenovo URL acceptance recon (folded in)**. HP first because path #1 (curl_cffi + HTTP/1.1) is empirically validated on BestBuy's identical Akamai gate (per memory `project_hp_coverage_gap`), needs no new deps, and closes a documented gap on an already-shipped fetcher. ASUS www second because recon is already complete (2026-05-04) and the build is well-scoped. Lenovo URL acceptance is a small recon sub-task that ships alongside.

- [ ] **HP coverage gap fix** — `scrapers_lib/tier2/hp.py` returns 12 of ~32 visible specs per tile (config-picker categories only; the ~20 "Tech Specs" categories — Dimensions / Ports / Weight / Warranty / Audio / Sensors / Security hardware / Power supply — are client-side hydrated behind HP's browser bot gate). Two upgrade paths:
  - **Recon prerequisite (first action of the HP fix):** Path #1 was validated on BestBuy's Akamai gate, not HP's. Before committing to it as the solution, run a probe (curl_cffi + HTTP/1.1 + homepage warming against a current HP `/shop/pdp/` URL) and inspect whether the **Tech Specs** section (Dimensions / Ports / Weight / Audio / Sensors / Power supply) actually appears in the response body — those specs are documented as client-side hydrated, so clearing the HTTP-level bot gate does NOT automatically deliver them. Three possible recon outcomes:
    - **(a)** Tech Specs present in initial HTML → Path #1 alone is sufficient; proceed to implementation.
    - **(b)** Path #1 clears the gate but Tech Specs are loaded via separate XHR → identify the hydration endpoint, replicate the call via the same curl_cffi session.
    - **(c)** Path #1 fails to clear HP's gate (less likely given Akamai class match) → pivot to Path #2 below.
  - **Path #1 (lead):** `curl_cffi` with Chrome impersonation forced onto HTTP/1.1. Empirically validated on BestBuy's identical Akamai gate in Wave 2c (see `scrapers_lib/tier3/bestbuy.py` for reference implementation). Dep already installed (`curl_cffi>=0.7`). No new deps required. Borrow `_fetch_pdp`-style session pattern from `tier3/bestbuy.py`; add homepage warming.
  - **Path #2 (fallback if recon outcome (c), or if more depth needed later):** HP QuickSpecs PDFs at `h20195.www2.hp.com` — already mentioned in `hp.py` docstring as feasible-but-unimplemented. Gold standard, deeper data than the PDP itself, but ~1 day more work and requires a fuzzy SKU→docID bridge plus `certifi`-based SSL trust fix for the host.
  - Recommendation: recon first; ship Path #1 (alone or with XHR-replication per outcome (b)) if it works; revisit Path #2 only if recon outcome (c) or if a future demo flags insufficient HP coverage.

- [ ] **ASUS www.asus.com expansion** — extend ASUS coverage from ROG-only (Wave 2b shipped `rog.asus.com` parsing) to non-ROG product lines (Zenbook, Vivobook, TUF Gaming) on `www.asus.com`. **Recon DONE 2026-05-04.** Findings:
  - **URL shape:** `www.asus.com/<region>/laptops/for-{home,gaming}/<line>/<model>/techspec/`
  - **Anti-bot:** open (no DataDome), same posture as `rog.asus.com`
  - **Render:** Nuxt SSR — specs live in a `window.__NUXT__=(function(...){...}(...))` IIFE (~204 KB inner). httpx-only viable, no Playwright needed.
  - **Class family:** `TechSpec__*` (e.g. `TechSpec__itemName__an9aU`), distinct from ROG's `ProductSpec__*` → parallel parser, not extension of existing ROG parser.
  - **Confirmed live URLs (3) for fixtures + integration test:**
    - `https://www.asus.com/us/laptops/for-home/zenbook/asus-zenbook-14-ux3405/techspec/`
    - `https://www.asus.com/us/laptops/for-home/vivobook/vivobook-16-laptop-f1605/techspec/`
    - `https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2025/techspec/`
  - **Working UA:** existing `_DEFAULT_USER_AGENT` constant in `scrapers_lib/tier2/asus.py`.
  - **New dep:** **PyMiniRacer** (V8 in-process) to evaluate the Nuxt IIFE; Node subprocess as fallback if Windows wheel unavailable.
  - **Architectural call:** new module `scrapers_lib/tier2/asus_www.py`; existing `asus.py` (ROG) untouched; dispatcher in registry routes by host (`rog.asus.com` → existing parser, `www.asus.com` → new parser).
  - **Public API impact:** none. Same `fetch_asus_product` entry point, same `SOURCE = "asus"`, same `ProductSnapshot` output.
  - **Build scope:** ~1.5 days.

- [ ] **Lenovo URL acceptance recon** — `scrapers_lib/tier2/lenovo.py` currently rejects non-PSREF URLs (`_extract_product_key` raises `ValueError` if host is not `psref.lenovo.com`; line ~197). Demo 2's consumer workflow expects callers to feed the natural consumer PDP URL (`lenovo.com/p/...`), which would fail today. **Recon scope:** does the consumer PDP carry a discoverable PSREF link (page metadata, footer, JSON-LD `mainEntity`, etc.)? If yes, extend the fetcher to auto-resolve `lenovo.com/p/...` → PSREF `ProductKey` before calling `LoadSpecData`. If no, document the constraint (consumers must pass PSREF URLs) and ship a separate `resolve_lenovo_url` helper for future search-bridge work. Build estimate after recon — likely small if PDP carries a link, larger if a search bridge is needed. Public API impact: none (extending `fetch_lenovo_product` to accept both URL types is additive).

## Wave 2f — Tier 2 expansion: Acer + MSI (greenfield)

Driver: completing the six-brand Tier 2 manufacturer set so Demo 2's `Competitor Columns` schema can be filled for Acer and MSI products. Both are **greenfield** — scaffolds were removed at v1.0.0 (per Wave 4 closure notes) and recon is a hard prerequisite per `docs/ADDING_A_SOURCE.md`. Wave 2f kicks off after Wave 2e closes.

Recommended order: **Recon both → build in parallel post-recon**. Acer and MSI share no surface (different hosts, different stacks), so once each one's spec-acquisition pattern is known they can be built independently and tested independently.

- [ ] **Acer Tier 2 fetcher** — recon required first. Identify spec-acquisition pattern (HTML scrape vs internal API vs hydrated state-JSON), bot-gate posture, and class-family / selector strategy. Build estimate after recon.

- [ ] **MSI Tier 2 fetcher** — recon required first per `docs/ADDING_A_SOURCE.md`. Build estimate after recon.

## Deferred (not blocking any current work)

- Demo 2 (Hot Response) consumer project — library side is partial today (Dell / HP / Lenovo / ASUS-ROG shipped; HP coverage thin); Wave 2e + Wave 2f close the remaining gaps. Consumer scaffold deferred until library reaches ~80–90% coverage across all six brands and the user chooses to build it.
- Demo 3 (Gaming Radar) consumer project — library side is shipped (Wave 3); consumer scaffold deferred until user chooses to build it.
- BestBuy Developer API activation — fetcher is shipped and unit-tested but dormant until a credential lands (see `project_bestbuy_api_dormant`).
- Additional Tier 1 sources: Walmart affiliate API, YouTube Data API (channel monitoring).
- Additional Tier 2 sources: forums, more manufacturers.
- Additional Tier 3 sources: Newegg, Target, Costco.
- Plugin registration API (fetcher signature is already plugin-compatible).
- Spec-vocabulary normalization helpers.
- PyPI publication.
- Distributed Scheduler coordination across multiple workers.
