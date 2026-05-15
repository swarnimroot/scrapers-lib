# scrapers-lib — Tasks and Roadmap

**Status:** stable &nbsp;·&nbsp; **Last updated:** 2026-05-14 (v1.7.0 YouTube `audio_fallback` — local STT for POT-gated captions) &nbsp;·&nbsp; **Library version:** 1.7.0

This is the operational roadmap. Library-intrinsic priorities lead — the downstream consumer projects (Demo 2, Demo 3, Pilot 1) are now built externally in their own repos and no longer drive the order in which library work happens. Wave history below records the past order accurately, including which consumer drove each Tier 2 / Tier 3 wave; future direction is library-intrinsic.

---

## Current state

**Last updated:** 2026-05-14 (v1.7.0 shipped: `fetch_youtube_transcript` gained opt-in `audio_fallback` — POT-gated or caption-absent videos route to local yt-dlp + faster-whisper speech-to-text)

- **Latest tag:** **v1.7.0** (2026-05-14) — Tier 1 re-open (not part of the Tier 2 "2x" wave series; same standalone-version convention as v1.4.0). `fetch_youtube_transcript` gained two optional kwargs (`audio_fallback: bool = False`, `audio_model: str = "small.en"`). YouTube extended Proof-of-Origin Token gating to the caption (timedtext) endpoint through 2025-2026, so ~50% of caption requests from residential IPs now fail with `BlockedError`. With `audio_fallback=True`, a `BlockedError` or an empty caption result (`[]`, captions disabled) routes to a local speech-to-text path — yt-dlp downloads audio-only, faster-whisper transcribes on CPU (`small.en`, int8); a real caption hit short-circuits it. Same chunked `RawMention` output + `&t=<s>s` deep-links — downstream consumers need no changes. New optional `[youtube-audio]` extra (`yt-dlp>=2024.10`, `faster-whisper>=1.0`; lazy-imported, NOT in the core install). Public API additive — default behavior byte-for-byte identical to v1.6.0; v1.0 surface stays frozen. Prior tag: v1.6.0 (Wave 2i: HP PDP shape dispatcher — STO fallback + `HPProductNotFoundError`, 2026-05-13). Before that: `parse_hp_product_page` gained a three-way dispatcher keyed off `slugInfo.templateKey` + presence of CTO/STO data: (a) CTO customizer URLs (slugs `…av-1`) — unchanged behavior (~23-26 specs per tile via config-picker + async). (b) STO SKU-final URLs (slugs `…nr`) — new path emitting one snapshot per URL with `source_id=productInitial.sku`, specs from the same async `pdpTechSpecs` endpoint (28+ categories), prices/rating/image/title from `productInitial` + `productInitialPrice` + `pdpImages` (filtering `.mp4`/`.webm`/`.mov`). (c) Delisted slugs (`templateKey="home"`, HP silently redirects to shop homepage) — raises new typed `HPProductNotFoundError(RuntimeError)`. Triggered by an external consumer hitting `AttributeError` on `…nr` URLs (the v1.5 chain `.get("pdpCTOConfiguration", {})` did not fire its default because STO sets the value to `None`, not missing). Public API additive — CTO callers unchanged; STO callers go from crash to working snapshot; consumers can `except HPProductNotFoundError` to skip dead slugs cleanly. No new dependencies. Prior tags: v1.5.0 (Wave 2h: Dell `include_options` + `ComponentOption`, 2026-05-13), v1.4.0 (article fetcher upgraded; `curl_session` module graduated; notebookcheck added, 2026-05-12), v1.3.1 (Wave 2g: `warmed_curl_session()` graduated into `tier2/base`, 2026-05-07), v1.3.0 (Wave 2f: Acer + MSI greenfield, 2026-05-07), v1.2.1 (2026-05-07, `emit_all_comments` kwarg patch), v1.2.0 (Wave 2e: HP coverage fix + ASUS www, 2026-05-07), v1.1.0 (Wave 2d: BestBuy reviews pagination, 2026-04-22), v1.0.0 (public API freeze, 2026-04-22).
- **Wave history (all shipped):** Wave 0 (scaffold) → Wave 1 (core, v0.1.0) → Wave 2a (Dell, v0.2.0) → Wave 2b (HP/Lenovo/ASUS, v0.3.0) → Wave 2c (BestBuy + Amazon, v0.4.0) → Wave 3 (RSS/article/Reddit/YouTube, v0.5.0) → **Wave 4 (v1.0 readiness, v1.0.0)** → Wave 2d (BestBuy reviews pagination, v1.1.0) → Wave 2e (HP coverage fix + ASUS www, v1.2.0) → **Wave 2f (Acer + MSI greenfield, v1.3.0)** → **Wave 2g (warmed_curl_session helper graduated, v1.3.1)** → **v1.4.0 (article fetcher upgraded; `curl_session` module graduated; notebookcheck added)** → **Wave 2h (Dell configurator option menu, v1.5.0)** → **Wave 2i (HP PDP shape dispatcher: STO fallback + delisted-slug typed error, v1.6.0)** → **v1.7.0 (YouTube `audio_fallback`: local STT for POT-gated captions)**.
- **In progress:** none — v1.7.0 shipped 2026-05-14.
- **Next direction:** **Library is at a stable resting state at v1.7.0.** No further library work planned — consumer projects (Demo 2 / Demo 3 / Pilot 1) are built externally and the library is sufficient for them. Library-intrinsic candidates (plugin / extension API; PyPI publication; Tier 1/3 source catalog: Walmart affiliate API, YouTube Data API channel monitoring, Newegg / Target / Costco, forums) remain available but deferred until concrete demand arrives.
- **Test state:** **see CHANGELOG `[1.7.0]` for the post-release baseline** (1169 passed, 22 skipped — +22 new unit tests in `tests/tier1/test_youtube_audio.py`; no new gated-live integration tests).
- **New dep:** none in the core install. `yt-dlp>=2024.10` + `faster-whisper>=1.0` ship only as the optional `[youtube-audio]` extra (lazy-imported; consumers that don't enable the fallback pay nothing at install/import).
- **Dev env:** `.venv/` with all library deps (pydantic, httpx, curl_cffi, beautifulsoup4, playwright, playwright-stealth, feedparser, trafilatura, youtube-transcript-api, diskcache, python-dotenv, py_mini_racer). Chromium installed via `playwright install chromium`. `yt-dlp` + `faster-whisper` are an OPTIONAL `[youtube-audio]` extra — not in the base .venv deps list; install with `pip install -e ".[youtube-audio]"` to exercise the audio fallback.
- **Open questions:** none blocking library work.

### How to resume in a new session

Say "Resume scrapers-lib" (or similar). Claude will read memory files (auto-loaded), this Current state block, and `git log --oneline -10`, then summarize and propose the next step before touching anything.

### End-of-session ritual

Say "wrap this session" (or similar). Claude will commit any in-flight work (or mark it WIP), update this Current state block, check off completed items below, and add a line to `CHANGELOG.md` `[Unreleased]` if anything user-visible changed.

---

## Downstream consumers (external)

The downstream consumer projects below are **built externally** in their own repos as siblings of `scrapers-lib`. They drove the library's past wave order — that history is recorded accurately in the wave entries below — but they no longer drive future library work. Library-intrinsic priorities lead now (see `## Library-intrinsic next directions`).

- **Pilot 1 — product sentiment & reviews (pivoted 2026-04-22 from Demo 1).** PC-manufacturer-POV tool that reads consumer sentiment across the library's sources to inform product / pricing / positioning / warranty decisions. Out-of-tree consumer project; brainstorm phase per memory `project_demo1_pulse_check.md`. Uses hybrid LLM routing (local for classification volume; Anthropic for synthesis quality). The pre-scrapers-lib standalone "Pulse Check" 9-script pipeline was the previous attempt; treated as data-shape witness only, not a template (see memory `project_demo1_not_a_scraping_reference.md`).
- **Demo 2 — Hot Response (manufacturer spec comparisons).** Out-of-tree consumer project that scrapes Dell / HP / Lenovo / ASUS / Acer / MSI manufacturer pages for maximum spec detail per product, targeting its own **`Competitor Columns` 83-row spec schema** (CPU / GPU / Memory / Display / Battery / I/O / Thermals / Design). Drove Waves 2a/2b/2e/2f; six-brand Tier 2 set was completed at v1.3.0. Per-brand raw coverage estimate at v1.3.0: Lenovo PSREF ~95%, ASUS ROG ~85–90%, ASUS www non-ROG ~85–90%, Acer ~85–90%, MSI ~80–85%, HP ~70–80% (Wave 2e closed the prior browser-gate gap), Dell ~75–80%. Library scope ended at raw acquisition; downstream parsing / normalization / spreadsheet population live in the consumer repo. Status / Segment / Year / Sub Brand columns are editorial and remain manual.
- **Demo 3 — Gaming news radar.** Out-of-tree consumer project aggregating ~20 gaming news / reviewer sites + Reddit gaming subs for trend and sentiment. Drove Wave 3 (RSS / article / Reddit / YouTube fetchers shipped at v0.5.0).

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
- [x] ~~`tier2/acer.py`~~ — **Deferred at this wave (post-demo).** Not required for Demo 2 max-spec comparison at the time; Dell/HP/Lenovo/ASUS covered the four major gaming-laptop manufacturers. Subsequently shipped in Wave 2f at v1.3.0 (see below).
- [x] ~~`tier2/msi.py`~~ — **Deferred at this wave (post-demo)**, same rationale as Acer. Subsequently shipped in Wave 2f at v1.3.0 (see below).
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

- [x] **HP coverage gap fix** — *(Recon resolved 2026-05-05 at commit 1a79fe7; build shipped this session.)* `tier2/hp.py` now makes two HTTP calls on a single warmed `curl_cffi` + Chrome + HTTP/1.1 session: PDP HTML for config-picker tiles (~12 categories) plus the slug-keyed GraphQL endpoint `/us-en/shop/app/api/web/graphql/page/pdp%2F<slug>/async` for product-wide Tech Specs (~23-26 categories — Dimensions / Weight / External I/O Ports / Audio Features / Network interface / Battery Recharge Time / Power supply / Webcam / Warranty / etc., set varies by product family). Per-tile values overlay async values on overlap; async-fetch failure logs at INFO and falls back to config-picker-only data (graceful degradation, mirrors v1.1 12-category ship). Both arrays use the same `{name, tooltip, value:[{value, subheading}]}` row shape — except the async inner `value` is sometimes a list of strings, joined with `<br/>` so the existing flattener handles both shapes uniformly. Public API unchanged: same `fetch_hp_product` entry point, same `ProductSnapshot` output (richer `specs` dict + `config_summary`). New optional `warm` / `impersonate` kwargs on `fetch_hp_product`; new optional `async_techspecs` kwarg on `parse_hp_product_page` for testability. New `raw.spec_source` value `"pdpCTOConfiguration+pdpTechSpecs"` (vs `"pdpCTOConfiguration"`) marks merged snapshots. 71 HP unit tests passing (54 pre-build + 17 new across `TestDeriveAsyncUrl` / `TestExtractAsyncSpecs` / `TestParseHpProductPageWithAsync`). Live integration test asserts async-only categories present and `spec_source` shows merge. Path #2 (QuickSpecs PDF bridge) remains deprioritized — held in reserve only if a future demo needs deeper coverage than ~23 categories.

- [x] **ASUS www.asus.com expansion** — *(Recon resolved 2026-05-04; build shipped 2026-05-07.)* New module `scrapers_lib/tier2/asus_www.py` covers Zenbook / Vivobook / TUF Gaming. The Nuxt SSR `__NUXT__=(function(...){...}(...))` IIFE is located via `(?:window\.)?__NUXT__\s*=\s*\(function\(`, paren-balanced to extract the full ~200 KB expression, evaluated via `py_mini_racer` (in-process V8), then `state.PDPage.PDTechSpecM2.SpecList` walked for `{Title, Content}` rows (typically 22-28 categories: 28 on consumer Zenbook/Vivobook, 22 on TUF gaming). Each `Content` cell HTML-decodes and br-splits to per-SKU rows (handles `<br>`, `<BR>`, and `</br>` sic on Vivobook); residual `<sup>` / `<span>` tags stripped; first-occurrence dedupe. **All HP-gap axes (Dimensions / Weight / I/O Ports / Audio) confirmed present across all three product lines.** Plain httpx is sufficient (no DataDome on `www.asus.com`). Host dispatch in `tier2/asus.py` `fetch_asus_product` routes `www.asus.com` URLs here while `rog.asus.com` stays on the in-module ROG parser; both share `SOURCE = "asus"`. Public API unchanged. New dep `py_mini_racer>=0.6` added to `pyproject.toml`. 60 new unit tests in `tests/tier2/test_asus_www.py`; 1 gated live integration test added to `test_asus_integration.py`. `raw.spec_source` = `"www_asus_pd_techspec_m2"` marks www-sourced snapshots. **Original recon findings (2026-05-04):**
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

- [x] **Lenovo URL acceptance recon** — *(Resolved 2026-05-07 as NO; document constraint, defer search-bridge.)* Web research determined `lenovo.com/p/...` consumer PDPs carry no discoverable PSREF link. Evidence: Google `site:lenovo.com "psref.lenovo.com"` returns zero hits on `/p/` PDPs (only `psref.lenovo.com/*` self-results); third-party PSREF tools (`thinkstation-specs.com`, `dennwc/psref`, `specsdata.com`) all enter via MTM (Machine Type), never via consumer slug. Bonus finding: `www.lenovo.com` is itself bot-gated (curl_cffi+HTTP/1.1 needed, like HP/BestBuy) — even if the link existed, plain httpx wouldn't reach it. Outcome: Wave 2e ships the existing `tier2/lenovo.py` PSREF-only constraint as-is. The `_extract_product_key` ValueError on non-PSREF hosts at line ~197 is now the documented contract. A search-bridge resolver (`psref.lenovo.com/search/?q=<slug>` → ProductKey) remains a viable future path if Demo 2's consumer-flow ergonomics demand it; deferred out of Wave 2e because the LoadSpecData JSON endpoint already delivers the schema we need from PSREF URLs and the recon revealed no architectural shortcut.

## Wave 2f — Tier 2 expansion: Acer + MSI (greenfield) *(shipped v1.3.0, 2026-05-07)*

**Closed 2026-05-07 at v1.3.0.** Greenfield scaffolds for the remaining
two 0%-coverage manufacturers landed and the six-brand Tier 2 set is
complete. Both fetchers are additive on top of the frozen v1.0 public
API.

- [x] **Acer Tier 2 fetcher** — `tier2/acer.py` `fetch_acer_product`
  (`@register("acer")`). Plain-httpx (no anti-bot) against
  `acer.com/<region-locale>/<brand>/laptops/<model>/pdp/<SKU>`; the
  `/pdp/<SKU>` suffix is required (bare model URLs return a model-overview
  page without specs). Parses 13 SSR `<table class="agw-table agw-table_techSpec">`
  blocks via `tier2.base.parse_spec_table()` into a flat `specs` dict
  (~60+ unique label keys covering Operating System / Processor /
  Graphics / Memory / Storage / Display / Battery / I/O / Wireless /
  Camera / Keyboard / Touchpad / Audio / Dimensions / Weight / Security
  / Sensors; set varies per SKU). JSON-LD Product enriches `title` /
  `brand` / `image_url` / `price` / `currency` / `availability_text`.
  Per-SKU granularity. `raw.spec_source` = `"ssr_table"`. 57 unit tests
  in `tests/tier2/test_acer.py` against Aspire 7 Intel + Predator
  Helios Neo 16s AI + Nitro V 16s AI fixtures.

- [x] **MSI Tier 2 fetcher** — `tier2/msi.py` `fetch_msi_product`
  (`@register("msi")`). `curl_cffi` with Chrome TLS impersonation +
  warmed session (visit `https://us.msi.com/` first, brief sleep, then
  PDP) — Akamai HTTP-layer gate on plain `httpx` returns 403; the warmed
  `curl_cffi` primitive (same one HP/BestBuy use) clears it.
  **`/Specification` is universal across MSI's product lines** (gaming
  Raider / Crosshair + premium Stealth-AI), hosting a single `<table>`
  with **column-per-SKU** layout (`thead` row of SKU column headers +
  `tbody` rows pairing `<th>` label with `<td>` per SKU column, 27-31
  spec rows per page). One snapshot per `<thead>` SKU column. Bare
  `/Laptop/<slug>` URLs fetch `/Specification` first; on parse failure
  they fall back to the main page's JSON-LD `ItemList` (~11-field
  highlights summary, present only on newer AI/Stealth lines). New
  optional `warm` and `impersonate` kwargs on `fetch_msi_product`
  (mirroring HP). `raw.spec_source` = `"specification_table"` (primary)
  or `"jsonld_itemlist"` (fallback). 107 unit tests in
  `tests/tier2/test_msi.py` against Stealth 16 AI+ B3WX (main + spec)
  + Raider 16 Max HX B2WX (main + spec) + Crosshair 16 HX E14WX (spec)
  fixtures. `scripts/msi/fetch_fixtures.py` is the re-runnable fixture
  refresh probe.

- [x] Per-source coverage rows added to `docs/ARCHITECTURE.md` §11
  (replacing the prior `Acer, MSI: Deferred (post-demo)` row).
- [x] Per-manufacturer pattern entries added to
  `docs/ADDING_A_SOURCE.md` §4 (replacing the prior deferred row).
- [x] CHANGELOG `[1.3.0]` entry; `_version.py` bumped 1.2.1 → 1.3.0;
  tag `v1.3.0`.

## Wave 2g — Tier 2 base helper: `warmed_curl_session()` *(shipped v1.3.1, 2026-05-07)*

**Closed 2026-05-07 at v1.3.1.** The warm `curl_cffi` + Chrome + HTTP/1.1
+ homepage-warming bootstrap pattern that three modules had been
duplicating (`tier2/hp.py` from Wave 2e, `tier2/msi.py` from Wave 2f,
`tier3/bestbuy.py` from Wave 2c) graduated into a shared
`scrapers_lib.tier2.base.warmed_curl_session()` context manager. Pure
refactor — public API unchanged on top of the frozen v1.0 surface.

- [x] **`tier2.base.warmed_curl_session()` helper introduced.** Context
  manager yielding a warmed `curl_cffi.requests.Session` configured
  with Chrome TLS impersonation and `CurlHttpVersion.V1_1`. Signature
  `warmed_curl_session(homepage, *, impersonate="chrome", warm=True,
  warm_delay=1.0, warm_headers=None, timeout=30.0)`. `curl_cffi`
  imported lazily inside the helper so callers of unrelated `tier2.base`
  symbols don't pay the import cost. Warm-up failures are swallowed
  and logged at DEBUG (best-effort).
- [x] **Three migration sites:** `tier2/hp.py` (`_fetch_pdp_with_techspecs`),
  `tier2/msi.py` (`_fetch_msi_html`), and `tier3/bestbuy.py`
  (`_fetch_pdp` and `_iter_reviews_pages`) all now open their sessions
  via the helper instead of constructing the `curl_cffi` Session inline.
  DEBUG warm-failure log text unified across all three modules from
  per-module prefixes to a single
  `"warmed_curl_session(<homepage>): warm failed: ..."`.
- [x] **Public API unchanged.** `fetch_hp_product`, `fetch_msi_product`,
  and `fetch_bestbuy_reviews` all preserve their `warm: bool = True`
  and `impersonate: str = "chrome"` kwargs verbatim; observable behavior
  unchanged.
- [x] **+9 new unit tests** in `tests/tier2/test_base.py::TestWarmedCurlSession`;
  unit suite goes 1073 / 20 → 1082 / 20.
- [x] **No new dependencies.** `curl_cffi>=0.7` already shipped in Wave 2c.
- [x] Helper documented in `docs/ADDING_A_SOURCE.md` §4.1 (generic
  pattern types — new "Reusable primitive" subsection).
- [x] CHANGELOG `[1.3.1]` entry; `_version.py` bumped 1.3.0 → 1.3.1;
  tag `v1.3.1`.

## v1.7.0 — YouTube audio fallback (Tier 1 re-open) *(shipped 2026-05-14)*

**Closed 2026-05-14 at v1.7.0.** The external gaming-chatter consumer
hit a ~50% caption-block rate: YouTube extended Proof-of-Origin Token
enforcement to the caption (timedtext) endpoint through 2025-2026, so
roughly half of caption requests from residential IPs now fail with
`BlockedError` (`PoTokenRequired` / `IpBlocked` / `RequestBlocked`).
Swapping caption libraries does not help — yt-dlp's caption path hits
the same gated endpoint. v1.7.0 adds an opt-in local speech-to-text
fallback. Additive on the frozen v1.0 public API.

- [x] **Two new optional kwargs** on `fetch_youtube_transcript`:
  `audio_fallback: bool = False` and `audio_model: str = "small.en"`.
  Default behavior byte-for-byte identical to v1.6.0; v1.0 surface
  stays frozen.
- [x] **New `_youtube_audio` module.** With `audio_fallback=True`, two
  conditions route to the audio path: (a) the caption fetch raises
  `BlockedError`, (b) it returns `[]` (uploader disabled captions / no
  track in requested languages). A real caption hit short-circuits the
  audio path. yt-dlp downloads audio-only; faster-whisper transcribes
  locally on CPU (`small.en` default, int8). Output is the same chunked
  `RawMention` list with the same `&t=<s>s` deep-links — downstream
  consumers need no changes. Video-unavailable markers
  (private/deleted/age-gated/region-locked/members-only/upcoming-livestream)
  return `[]` like the captions path; other yt-dlp failures raise
  `BlockedError`.
- [x] **New optional `[youtube-audio]` extra** = `yt-dlp>=2024.10`,
  `faster-whisper>=1.0`. Lazy-imported, NOT in the core install; opt in
  with `pip install -e ".[youtube-audio]"`. First audio call lazily
  caches ~150 MB of small.en weights via the HuggingFace hub.
  Consumers that don't enable the fallback pay nothing at
  install/import.
- [x] **+22 new unit tests** in `tests/tier1/test_youtube_audio.py`.
  Unit suite: **1169 passed, 22 skipped** (was 1147 / 22 at v1.6.0).
  No new gated-live integration tests.
- [x] **No new dependencies in the core install** — yt-dlp +
  faster-whisper ship only as the optional extra.
- [x] Docs updated: `README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`
  (§11 YouTube row, §14 tag list), `docs/CONSUMER_GUIDE.md` (install +
  §9 YouTube row + empty-list reasons), `docs/SOURCE_ATLAS.md` (source
  table + §5.4 YouTube entry), `docs/TASKS.md` (Current state + this
  closed-wave entry), `CHANGELOG.md` (`[1.7.0]` entry).
- [x] CHANGELOG `[1.7.0]` entry; `_version.py` bumped 1.6.0 → 1.7.0;
  tag `v1.7.0` (commit `39330a7`).

## Wave 2i — HP PDP shape dispatcher *(shipped v1.6.0, 2026-05-13)*

**Closed 2026-05-13 at v1.6.0.** External consumer surfaced an
`AttributeError` from `fetch_hp_product` on HP's SKU-final
preconfigured URLs (slugs typically `…nr`, e.g. `ap0097nr`,
`fa2047nr`), and a different `RuntimeError` on a 17.3" OMEN URL
(`a7jp9av-1`). Recon traced the failures: STO PDPs set
`pdpCTOConfiguration: None` (key exists, value is None) so the v1.5
`.get("pdpCTOConfiguration", {})` default never fired and the chain
crashed on `None.get("configurations")`; the 17.3" URL is actually
**delisted** — HP silently rewrites discontinued slugs to the shop
homepage at the CMS layer (`templateKey="home"`, no product surfaces).
Wave 2i closes both gaps with a three-way dispatcher and a typed
exception. Additive on the frozen v1.0 public API.

- [x] **Recon** against three URL shapes (AV-code customizer, STO `…nr`,
  17.3" outlier). Confirmed all three are status 200 but only the first
  carries CTO data. STO PDPs carry a rich `productInitial` +
  `productInitialPrice` + `pdpImages` payload plus a JSON-LD Product
  block (absent on CTO), and the same async `pdpTechSpecs` endpoint
  returns 28+ categories. The 17.3" URL silently redirects to the shop
  homepage (`templateKey="home"`). Recon probe committed at
  `scripts/hp/recon_pdp_shapes.py`; fixtures at
  `tests/tier2/fixtures/hp/recon_av_a58a5av1.html`,
  `tests/tier2/fixtures/hp/recon_nr_ap0097nr.html`,
  `tests/tier2/fixtures/hp/recon_nr_ap0097nr_async.json`,
  `tests/tier2/fixtures/hp/recon_av_a7jp9av1_173.html`, plus a JSON
  cross-URL summary.
- [x] **New typed exception** `HPProductNotFoundError(RuntimeError)` in
  `tier2/hp.py`. Module-scoped (not re-exported at the package top
  level — HP-specific; generalize when a second source needs it).
  Subclass of `RuntimeError` so existing `except RuntimeError` handlers
  still catch.
- [x] **New STO parser** `_parse_sto_snapshot()` in `tier2/hp.py`. Pulls
  `source_id` from `productInitial.sku`, title from `productInitial.name`
  (cleaner than JSON-LD `name` — observed template rot on HP CTO PDPs),
  brand from `productInitial.brand` (fallback to JSON-LD), prices from
  `productInitialPrice.{salePrice, regularPrice}`, rating/review_count
  from `productInitial.{rating, numReviews}` with type coercion + JSON-LD
  fallback, image from `pdpImages.fullImages` first non-video URL
  (skip `.mp4`/`.webm`/`.mov`), specs from the async `pdpTechSpecs`
  array. `raw.spec_source = "productInitial+pdpTechSpecs"` (or
  `"productInitial"` when async failed). Three small helpers: 
  `_rating_from_product_initial`, `_review_count_from_product_initial`,
  `_first_pdp_image_url`.
- [x] **Three-way dispatcher** in `parse_hp_product_page`. Order:
  (1) `templateKey != "pdp"` → `HPProductNotFoundError` (no point trying
  to parse a homepage redirect). (2) `pdpCTOConfiguration` populated +
  `configurations` non-empty → existing `_parse_cto_tiles()` path
  (unchanged from v1.5 — extracted from the inline loop into a named
  helper). (3) `productInitial` populated → new STO snapshot path.
  (4) Neither → opaque `RuntimeError("page structure may have
  changed")`. The v1.5 defensive idiom changed from `.get(..., {})` to
  `.get(...) or {}` to handle the `None`-value case STO PDPs use.
- [x] **+33 new unit tests** across `TestParseStoFallback` (14),
  `TestProductNotFoundError` (3), `TestNeitherCtoNorStoRaises` (1),
  `TestRatingFromProductInitial` (4), `TestReviewCountFromProductInitial`
  (4), `TestFirstPdpImageUrl` (6); one existing test in
  `TestParsePageStructuralFailures` updated to use `templateKey="pdp"`
  so it lands in the "neither CTO nor STO" branch instead of the new
  not-found branch. Unit suite: **1147 passed, 22 skipped** (was 1114 /
  22 at v1.5.0). No new gated-live integration tests.
- [x] **No new dependencies.** `curl_cffi>=0.7` and the existing
  `warmed_curl_session()` helper already in place.
- [x] Docs updated: `README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`
  (§11 HP row, §14 tag list), `docs/CONSUMER_GUIDE.md` (§9 HP row),
  `docs/SOURCE_ATLAS.md` (§6.2 HP entry), `docs/ADDING_A_SOURCE.md`
  (§4 HP row), `docs/TASKS.md` (Current state + this closed-wave entry),
  `CHANGELOG.md` (`[1.6.0]` entry).
- [x] CHANGELOG `[1.6.0]` entry; `_version.py` bumped 1.5.0 → 1.6.0;
  tag `v1.6.0`.

## Wave 2h — Dell configurator option menu *(shipped v1.5.0, 2026-05-13)*

**Closed 2026-05-13 at v1.5.0.** External need surfaced: a consumer
project wanted to scrape Dell `cty/pdp` (Configure-To-Order) URLs to
discover the **commodity options** Dell offers for a product line
(Processor / Graphics / Memory / Storage / Display / Keyboard / Battery
/ AC Adapter / OS / OS Language Pack). The v1.4 fetcher rejected those
URLs because the configurator page has no `[data-oc]` tile structure
— `_extract_tiles` returned empty and `RuntimeError: dell: no
configuration tiles found ... page structure may have changed` was
raised. Wave 2h closes that gap **without changing the supported entry
point** (still the shop-landing URL) by adding an opt-in kwarg that
internally rewrites the URL to the `cty/pdp` form, navigates to it
through the same stealth Playwright session, and attaches the parsed
menu to every emitted snapshot. Additive on top of the frozen v1.0
public API.

- [x] **Recon** against URL A (`/shop/cty/pdp/spd/<spd-slug>/<oc>`).
  Confirmed: page loads under existing `stealth_context` (no Akamai
  block); 10 hardware modules SSR'd in the initial HTML (no scrolling
  needed); each option card is `div.option.detailed-option[role="button"]`
  inside `div.accordion-box.single-column-accordion` and carries
  `data-option-id="<moduleId>-<sku>"` and `data-status="selected|
  available|unavailable"`; module title in sibling `h2.module-title`.
  Software / accessories modules use a different `<input type="radio">`
  DOM and are out of scope. Recon script committed at
  `scripts/dell/recon_configurator.py`; fixtures captured at
  `tests/tier2/fixtures/dell/cto_useac16250hbtshtgb_*.html`.
- [x] **New schema type `ComponentOption`** in `core/schemas.py`
  (Pydantic v2 BaseModel, `extra="forbid"`): `label: str`, `status: str`,
  `option_id: str`. Re-exported at the top level
  (`from scrapers_lib import ComponentOption`).
- [x] **New field `ProductSnapshot.options: dict[str, list[ComponentOption]]
  | None = None`**. Default `None` everywhere; populated only when the
  Dell fetcher is invoked with `include_options=True`. Additive — every
  existing call site continues to see `s.options is None` verbatim.
- [x] **New parser `parse_dell_configurator_options(html) -> dict[str,
  list[ComponentOption]]`** in `tier2/dell.py`. Pure function; walks
  every `div.accordion-box.single-column-accordion`, reads each option
  card's label / `data-option-id` / `data-status`. Module order mirrors
  on-page order; option order mirrors DOM order; duplicate
  `data-option-id` deduped within a module (first wins).
- [x] **URL constructor `_construct_cto_url(shop_url, oc)`** rewrites
  `/shop/<category-path>/spd/<spd_slug>` → `/shop/cty/pdp/spd/<spd_slug>
  /<oc>`, preserving scheme, host, and locale prefix (`/en-us`,
  `/en-uk`, ...). Returns `None` for unrecognized shapes.
- [x] **`fetch_dell_product` gained `include_options: bool = False`
  kwarg.** When true, after the techspecs loop, the same stealth session
  navigates to the derived `cty/pdp` URL (Akamai cookies stay warm),
  the parser runs, and the resulting dict is attached to every emitted
  snapshot via `parse_dell_product_page(..., configurator_options=...)`.
  Default `False` preserves historical performance / behavior verbatim
  (no extra page nav, `options=None` on every snapshot).
- [x] **+22 new unit tests** across `TestConstructCtoUrl` (4),
  `TestParseConfiguratorOptions` (11), `TestParseConfiguratorOptionsEdgeCases`
  (4), and `TestProductPageWithConfiguratorOptions` (2); unit suite
  goes 1092 / 21 → 1114 / 22 (the +1 skip is a new gated-live
  integration test `test_fetch_aurora_live_include_options`).
- [x] **No new dependencies.** Playwright + playwright-stealth +
  beautifulsoup4 already shipped.
- [x] Docs updated: `README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`
  (§1 file tree, §3.2 schema + new ComponentOption sub-section, §11 Dell
  row, §14 tag list), `docs/CONSUMER_GUIDE.md` (§9 Dell row),
  `docs/SOURCE_ATLAS.md` (§6.1 Dell entry).
- [x] CHANGELOG `[1.5.0]` entry; `_version.py` bumped 1.4.0 → 1.5.0;
  tag `v1.5.0`.

## Library-intrinsic next directions

With the downstream consumer projects external and the six-brand Tier 2
set complete, the library's roadmap turns inward. Three candidate
directions — none locked, all surfaced for selection:

- **(a) Plugin / extension API.** Let third-party consumer packages
  register fetchers without forking. The fetcher signature is already
  plugin-compatible (per the existing note in this doc and ARCHITECTURE
  §12.1); what's missing is the registration surface graduated for
  third-party use — e.g. `pip install scrapers-lib-walmart` auto-registers
  `fetch_walmart` via setuptools entry points. Implementation surface is
  small; the value is unblocking source growth from outside this repo.
- **(b) PyPI publication.** The library has been frozen at v1.0+ since
  2026-04-22 with stable docs, a CONSUMER_GUIDE, and 1082 / 20 unit
  tests. Now that consumers are external, `pip install scrapers-lib` is
  more ergonomic than `pip install -e ../scrapers-lib`. PyPI release
  also unblocks the entry-point flavor of (a).
- **(c) Source catalog (deferred-until-driven).** Additional Tier 1
  (Walmart affiliate API, YouTube Data API for channel monitoring),
  additional Tier 3 (Newegg, Target, Costco), and forums sit in the
  Deferred bucket below. They remain deferred without a consumer brief
  to drive specific recon — the right move is to ship one when an
  external consumer needs it, not speculatively.

Distributed Scheduler coordination stays deferred (no consumer
currently runs more than one worker against shared state).

## Deferred (not blocking any current work)

- Consumer projects (Demo 2 Hot Response, Demo 3 Gaming Radar, Pilot 1 product sentiment) are now built externally and don't constrain this library's roadmap.
- BestBuy Developer API activation — fetcher is shipped and unit-tested but dormant until a credential lands (see `project_bestbuy_api_dormant`).
- Additional Tier 1 sources: Walmart affiliate API, YouTube Data API (channel monitoring).
- Additional Tier 2 sources: forums, more manufacturers.
- Additional Tier 3 sources: Newegg, Target, Costco.
- Spec-vocabulary normalization helpers.
- Distributed Scheduler coordination across multiple workers.
