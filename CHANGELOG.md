# Changelog

All notable changes to scrapers-lib are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

## [0.5.0] — 2026-04-22

### Added
- `scrapers_lib.tier1.rss`: `fetch_rss_feed` (`@register("rss")` →
  `list[RawMention]`). Feedparser-based RSS / Atom fetcher that
  normalizes both dialects into one entry shape. Emits one
  `RawMention` per entry (discovery mode, `anchors=None`) or one per
  matching anchor (anchor-driven mode, `anchors=[...]`). Composes
  `raw_text` from `title` + `summary` + `content[0].value` with HTML
  tag-stripping; `published_at` from `published_parsed` /
  `updated_parsed`; `author` from `author` / `author_detail.name`
  fallback; `channel` from the feed's own title ("IGN Articles",
  "Test Gaming News"). `source` = caller's `source_slug` or derived
  from the feed URL's hostname (`feeds.ign.com` → "ign"). Deterministic
  `mention_id` via `rss_article_id(slug, guid)` suffixed with the
  anchor_id in anchor-mode. 41 unit tests (RSS 2.0 + Atom +
  edge-case-minimal fixtures), 2 gated live integration tests against
  IGN's live games feed.
- `scrapers_lib.tier1.article`: `fetch_article` (`@register("article")`
  → `list[RawMention]`). Trafilatura-based full-body extractor for
  follow-up when RSS summaries are teasers. Fetches via httpx, passes
  to `trafilatura.bare_extraction(with_metadata=True)`, emits one
  `RawMention` per anchor match (or one discovery mention). Populates
  `source_title`, `author`, `published_at`, `channel` (prefers
  trafilatura's `sitename` over `hostname`), `raw_text` (full article
  body, minimum 200 chars default) plus `raw.image` /
  `raw.description`. **Partial-success first**: returns empty list
  when trafilatura can't extract a usable body (paywall, 404 body
  chrome, too-short extraction) — never raises on quality; HTTP
  errors still raise for Scheduler retry. 38 unit tests (real IGN +
  Polygon article fixtures + synthetic paywall fixture, both
  different CMS shapes for §5.7 generality), 2 gated live
  integration tests.
- `scrapers_lib.tier1.reddit`: two registered fetchers. **Uses
  unauthenticated JSON endpoints** — PRAW OAuth self-service
  registration is closed per the Nov-2025 Reddit Responsible Builder
  Policy (`project_reddit_api_blocked` memory, empirically confirmed
  by a rejected formal application 2026-04-22). Public signatures
  stay PRAW-compatible (`sort` / `time_filter` / `limit` / `after`
  kwargs) so OAuth could swap in later without breaking callers.
  - `fetch_reddit_listing` (`@register("reddit")`) — pulls
    `reddit.com/r/<sub>/<sort>.json` (new / hot / top / rising, with
    `time_filter` for top) and emits one `RawMention` per post
    (`source_type="post"`). Accepts subreddit URLs, `r/Games`
    shorthand, or bare names.
  - `fetch_reddit_comments` (`@register("reddit_comments")`) — pulls
    `reddit.com/comments/<id>.json` and emits post + comments in
    pre-order depth-first traversal (post first, then comment tree
    with `source_type="comment"`, `parent_id` = post fullname
    `t3_<id>`). Skips `[deleted]` / `[removed]` content; counts
    unfollowed `kind="more"` stubs into `raw.more_count` for
    downstream awareness rather than recursing.
  - Deterministic IDs via `reddit_post_id` / `reddit_comment_id`
    helpers. 53 unit tests (real r/Games listing + comments
    fixtures + synthetic nested-tree fixture covering deletion,
    depth > 1, and more-stubs), 3 gated live integration tests.
- `scrapers_lib.tier1.youtube`: `fetch_youtube_transcript`
  (`@register("youtube")` → `list[RawMention]`). Pulls auto / manual
  captions via `youtube-transcript-api` 1.2+ and groups the very
  fine-grained per-word snippets (often 1–2 s each) into coherent
  **time-windowed chunks** (default 60 s ≈ ~150 words of speech per
  chunk — enough context for anchor matching and sentiment
  analysis). Emits one `RawMention` per chunk with `source_type=
  "transcript_chunk"`, `parent_id` = video ID,
  `raw.chunk_start_seconds` / `raw.chunk_end_seconds`, and a
  **deep-linked `source_url`** (`?t=<start>s`) that jumps the viewer
  back to the chunk's start moment. URL normalizer accepts
  `watch?v=` / `youtu.be/` / `embed/` / `shorts/` / `v/` forms plus
  bare 11-char IDs. Translates library-side exceptions:
  `NoTranscriptFound` / `TranscriptsDisabled` / `VideoUnavailable`
  / `AgeRestricted` / `InvalidVideoId` all map to empty-list
  (partial success); `RequestBlocked` / `IpBlocked` /
  `PoTokenRequired` raise `BlockedError` so the Scheduler can back
  off at the domain level. 46 unit tests (real Rick Astley transcript
  fixture + synthetic chunking edge cases including boundary snippet
  behavior, non-zero start offsets, and exception translation), 2
  gated live integration tests.
- `scrapers_lib.core.schemas`: `RawMention.attribution` widened from
  required to `Attribution | None` — unlocks **discovery-driven
  fetching** (`anchors=None` produces mentions without pre-filtering
  for downstream consumer analysis). All Tier 2 / Tier 3 fetchers
  continue to produce non-None attribution via URL-map; this change
  is additive, not a breaking API change for existing consumers.
- `scrapers_lib.core.attribution`: `attribute_regex_all(text, anchors)
  -> list[Attribution]` — multi-anchor matching variant that does NOT
  drop ambiguous multi-matches. Used by the four Wave 3 fetchers to
  emit one mention per matching anchor when a single article / post
  / comment / transcript-chunk is relevant to several anchors at
  once. Also adds `article_mention_id(slug, url)` ID helper.
- `scripts/rss/probe_feeds.py` + `README.md` — RSS / Atom feed
  discovery tooling. Probed 13 user-confirmed gaming-news sites,
  catalogued the canonical feed URL per site (VentureBeat's
  games-only subpath 403s but the site-wide feed works and is
  accepted per user decision to let all content flow through).
- Demo 3 feed catalog (12 gaming-focused sites + VentureBeat mixed)
  documented in `scripts/rss/README.md`.
- `tests/tier1/fixtures/` now contains per-fetcher subdirectories:
  `rss/`, `article/`, `reddit/`, `youtube/`.

### Removed
- `praw>=7.7` dependency — the library no longer requires PRAW since
  Reddit's closed self-service registration makes OAuth unreachable
  for this project. Fetcher signatures stay PRAW-compatible for
  future swap-in.

### Changed
- Bumped `pyproject.toml` + `scrapers_lib/__init__.py` +
  `README.md` version header to **0.5.0**.
- Full test suite: **762 passed, 16 skipped** (one gated live
  integration per active source — Dell / HP / Lenovo / ASUS / Amazon
  / BestBuy API / BestBuy reviews / RSS x2 / article x2 / Reddit x3 /
  YouTube x2).

## [0.4.0] — 2026-04-22

### Added
- `scrapers_lib.tier3.amazon`: two registered fetchers in one module —
  `fetch_amazon_product` (`@register("amazon")` → `list[ProductSnapshot]`)
  and `fetch_amazon_reviews` (`@register("amazon_reviews")` →
  `list[RawMention]`). Reconnaissance in `scripts/amazon/` confirmed that
  Amazon's `/dp/<ASIN>` PDP returns 2+ MB of real HTML on plain httpx with
  a current Chrome UA — counter to its Tier 3 reputation — carrying every
  product field (`#productTitle` / `#acrPopover` / `.priceToPay` /
  `#landingImage` / `#availability`) in stable containers plus the top
  ~8-12 reviews as inline `<li data-hook="review">` blocks with full
  body / rating / date / author / verified-purchase / helpful-count
  content. Specs come from a set of `<table class="prodDetTable">`
  expanders (Additional details, Memory, Battery, Ports & Slots, ...)
  merged into one `{key: value}` dict — ~60-75 rows on the Alienware 16
  Area-51 fixture, ~50-65 on the ASUS ROG Strix fixture. Brand extractor
  tries `#bylineInfo` → `#visitStoreDesktopUrl` → `#brandLogoHiResByline`
  (last two are the "premium PDP" variant for Consumer Electronics where
  Amazon hides `#bylineInfo` to avoid duplicate renders). The dedicated
  `/product-reviews/<ASIN>/` surface redirects unauthenticated clients
  to a sign-in wall and is auth-gated out of reach; PDP-inlined reviews
  are therefore the reachable subset (documented limitation — upgrade
  paths noted in `scripts/amazon/README.md`). Amazon stays in **Tier 3**
  because redesigns are frequent, IP-based rate limits apply on
  sustained traffic, and review coverage is partial by design. 78 unit
  tests (Alienware B0F8P6MRQT + ASUS ROG Strix B0DW1FVPK8 fixtures, two
  bylineInfo variants), 1 gated live integration test.
- `scripts/amazon/` — `probe_posture.py` + `README.md`. Single probe that
  exercises §3.8 bot-protection checks + §3.3–§3.5 structural signals
  against any Amazon URL (defaults to a search surface for cheap first
  passes); saves fixtures under `tests/tier3/fixtures/amazon/` with
  tight block-marker regexes anchored against `<title>`/form-action
  shapes to avoid false positives from stock error-UI template strings
  baked into legitimate PDP responses.
- `scrapers_lib.tier1.bestbuy_api`: `fetch_bestbuy_api_product`
  (`@register("bestbuy_api")`) — Tier 1 fetcher calling BestBuy's
  Developer API at `api.bestbuy.com/v1/products/<SKU>.json?apiKey=<key>`.
  Takes the BestBuy *website* URL (the form consumers naturally land on,
  e.g. `bestbuy.com/site/<slug>/<sku>.p?skuId=<sku>`), extracts SKU from
  the path or `skuId` query, calls the per-SKU lookup endpoint. Pulls
  `regularPrice` / `salePrice` / `onSale` / `dollarSavings` (on-sale:
  `salePrice` → `price`, `regularPrice` → `list_price`; not on sale:
  `regularPrice` → `price`, `list_price` None); `orderable` / online +
  in-store availability booleans → `in_stock`; `customerReviewAverage` /
  `customerReviewCount` → rating / review count; `manufacturer` +
  `modelNumber` → brand + model; leaf of `categoryPath` → category;
  `features[]` first 3 → `config_summary`; `details[]` flat list →
  `specs` dict. `largeFrontImage` → `image_url` with fallbacks to
  `image` / `thumbnailImage`. 403 on bad key / 404 on unknown SKU raise
  distinct exceptions. Credential loaded from `BESTBUY_API_KEY`
  environment variable (or passed explicitly via `api_key=`); missing
  key raises `RuntimeError` rather than silent failure. Unit tests
  run against synthetic fixtures matching the documented API schema —
  one on-sale in-stock Alienware SKU + one regular-price sold-out ASUS
  SKU to exercise both price paths and both availability paths; live
  integration test (`test_bestbuy_api_integration.py`) verifies the
  fixture shape against the real API and is gated behind both
  `SCRAPERSLIB_LIVE_TESTS=1` and `BESTBUY_API_KEY` so it stays silent
  until the user's key arrives. 55 unit tests + 1 doubly-gated live test.
- `scrapers_lib.tier3.bestbuy`: `fetch_bestbuy_reviews`
  (`@register("bestbuy_reviews")` → `list[RawMention]`) — reviews-only
  fetcher (retail product fields come from `tier1/bestbuy_api`). After
  a three-step recon escalation (plain httpx drops at transport;
  stealth Playwright fails at `net::ERR_HTTP2_PROTOCOL_ERROR`;
  `curl_cffi` with Chrome impersonation on HTTP/2 gets
  `HTTP/2 INTERNAL_ERROR` RST_STREAM across five Chrome versions), the
  fetcher uses `curl_cffi` with Chrome TLS impersonation forced onto
  **HTTP/1.1** — the combination that cleanly bypasses Akamai's
  HTTP/2-layer bot gate on `bestbuy.com/site/...` URLs. Warms against
  the homepage first, then fetches the PDP, then parses the inline
  `<script type="application/ld+json">` Product block for its
  `review[*]` list (typically 5 Review objects with `name` / `author.
  name` / `reviewBody` / `reviewRating.ratingValue`). Deterministic
  `mention_id` via `bestbuy_review_id(sku, author, body)` since
  JSON-LD carries no stable per-review ID. **Coverage caveats**:
  `published_at` is always `None` (JSON-LD Review objects on BestBuy
  PDPs lack `datePublished`); review count caps at ~5 per fetch
  (inline PDP cap). The `/site/reviews/name/<SKU>` surface carries
  dates + full pagination and is the upgrade path for a future wave.
  37 unit tests (Area-51 18" SKU 6628371 + Aurora 16X SKU 6630638
  Alienware fixtures via curl_cffi + HTTP/1.1), 1 gated live
  integration test. Total suite: **584 passed, 7 skipped** (one gated
  live integration per active source).
- `scripts/bestbuy/` — `probe_posture.py` (plain-httpx search-surface
  baseline) + `probe_pdp_stealth.py` (stealth Playwright escalation,
  kept as negative-result reference documenting the `ERR_HTTP2_
  PROTOCOL_ERROR` wall) + `README.md` telling the full three-step
  escalation story from plain httpx drop through stealth Playwright
  failure to the curl_cffi + HTTP/1.1 bypass. Fixtures under
  `tests/tier3/fixtures/bestbuy/`: `pdp_6628371.html`,
  `pdp_6630638.html`, plus the negative-result
  `search_alienware_gaming_laptop.html` (SPA shell, products
  XHR-hydrated).
- `scrapers_lib.core.attribution`: two new deterministic mention-ID
  helpers — `amazon_review_id(asin, review_id)` (Amazon's own
  R-prefix ID) and `bestbuy_review_id(sku, author, body)` (short
  hash, since BestBuy JSON-LD lacks stable per-review IDs).
- **Dependency**: `curl_cffi>=0.7` — Chrome TLS impersonation over
  `libcurl`, used by `tier3/bestbuy` to bypass Akamai's HTTP/2 bot
  gate on `bestbuy.com/site/...` URLs. Free, open-source, drop-in
  `requests`-like API. Same upgrade path documented in the HP
  coverage-gap memory for a future HP full-coverage rewrite.

## [0.3.0] — 2026-04-22

### Added
- `scrapers_lib.tier2.asus`: `fetch_asus_product` — plain-httpx fetcher for
  ASUS ROG marketing/spec pages (`rog.asus.com/laptops/<line>/<model>/spec/`).
  Walks every SSR'd `<h2>` with class prefix
  `ProductSpec__productSpecItemTitle__` (CSS-module hash suffix matched via
  startswith to survive ASUS rebuilds), takes its next-sibling `<div>`'s
  per-SKU `ProductSpec__rowItem__*` children as variants, dedupes in
  first-occurrence order, and emits **one `ProductSnapshot` per URL with
  20+ spec categories** — richest Tier 2 coverage so far, including
  Dimensions (cm + inches), Weight (kg + lbs), I/O Ports (Thunderbolt /
  HDMI / USB-C / USB-A specifics), Power Supply (wattage + voltage),
  Expansion Slots, Security (TPM), Wireless (Wi-Fi 7 / BT 5.4 version),
  AURA SYNC, Device Lighting, Microsoft Office / Xbox Game Pass bundle
  offers, Included in the Box. Multi-SKU variant rows are newline-joined
  with duplicates collapsed; `®`/`™` whitespace tightened (BS4 pulls
  those sub-elements out of their words with a stray space);
  `brand="ASUS"` normalized to the parent manufacturer for cross-vendor
  grouping (JSON-LD declares the sub-brand "ROG", preserved in
  `raw.jsonld_brand`). No prices — the ROG spec surface is marketing,
  and `shop.asus.com` is DataDome-gated (professional anti-bot; no free
  bypass). 50 unit tests (Strix G16 2025 + Zephyrus G16 2026 fixtures), 1
  gated live integration test. Total suite: 414 passed, 4 skipped.
- `scripts/asus/probe_asus_rog.py` — single reconnaissance probe: confirms
  shop.asus.com DataDome negative result, then fetches both committed ROG
  fixtures and prints the h2-based spec-section header outline. Plus
  `scripts/asus/README.md`.
- `scrapers_lib.tier2.hp`: `fetch_hp_product` — plain-httpx fetcher for HP
  shop PDPs (`www.hp.com/us-en/shop/pdp/<slug>`). Extracts the full page
  state from a hidden `<div id="data"><!-- {JSON} --></div>` block (a
  regex + `json.loads` away), walks
  `slugInfo.components.pdpCTOConfiguration.configurations` to emit one
  `ProductSnapshot` per pre-built "Recommended Configuration" tile
  (typically 3, per-tile `source_id`/`variant_key` = HP's
  `configCatentryId`, per-tile `price`/`list_price`/`image_url`). Each
  tile's ~12 config-picker categories (Processor and graphics, Memory,
  Storage, Display, etc.) serialize with current value on line 0 and
  alternatives on subsequent lines; HTML entities decoded. `brand`,
  `rating`, `review_count` enriched from JSON-LD. Parser walks
  categories by position so differing per-product-line naming (Pavilion
  merges Processor/Graphics/Memory into one category; Omen splits them)
  does not require code changes. Known limitation documented in
  `ARCHITECTURE.md` §11 + `ADDING_A_SOURCE.md` §4: the full "Tech Specs"
  section (Dimensions, Ports, Weight, Warranty, etc. — ~20 more
  categories) is client-side hydrated behind an aggressive Akamai bot
  gate that rejects both vanilla and stealth Playwright on `/shop/pdp/`
  URLs; HP QuickSpecs PDFs at `h20195.www2.hp.com` are a viable
  future-wave upgrade path. 54 unit tests (Omen Max + Pavilion 16z
  fixtures), 1 gated live integration test.
- `scripts/hp/` — two reconnaissance probes + README: `probe_hp_pdp.py`
  (plain-httpx baseline + §3.2 attribute scan that exposed the hidden
  `div#data` container after initial heuristics misfired) and
  `probe_hp_pdp_scroll.py` (stealth Playwright + scroll + XHR trace,
  kept as insurance even though static inspection of probe 1's output
  obviated the need for it).
- `scrapers_lib.tier2.lenovo`: `fetch_lenovo_product` — plain-httpx fetcher
  that extracts the PSREF `ProductKey` from a product URL and calls Lenovo's
  own `/api/product/Compare/LoadSpecData` endpoint. Returns one
  `ProductSnapshot` per URL (per-model-family granularity) with 50+ feature
  keys flattened from PSREF's nested `L1 > L2 > Features` tree; multi-option
  Features (e.g. two CPU SKUs) are serialized as newline-joined alternative
  rows so consumers can split and compare. No Playwright, no stealth,
  no new deps — PSREF has no bot gating. 47 unit tests (Legion Pro 7 16AFR10H +
  LOQ 15IRX10 fixtures), 1 gated live integration test.
- `scripts/lenovo/` — re-runnable PSREF reconnaissance probes: `probe_psref.py`
  (plain httpx baseline), `probe_psref_xhr.py` (Playwright XHR+iframe trace
  for SPA hydration discovery), `probe_psref_pdf.py` (PDF datasheet coverage
  witness using `pdfplumber` — installed into `.venv/` for the experiment
  only, **not** added to `pyproject.toml`).

## [0.2.0] — 2026-04-21

### Added
- `scrapers_lib.tier2._base`: shared Tier 2 parsing helpers — `parse_product_jsonld`
  (schema.org Product extraction across single / array / `@graph` shapes),
  `parse_inline_json` (`<script id="__NEXT_DATA__">` tags and `window.X = {...};`
  assignments with string-aware balanced-brace walker), `parse_spec_table`
  (`<table>` and `<dl>` patterns with optional container scoping),
  `normalize_spec_value` (whitespace + nbsp collapse), and `fetch_rendered_html`
  (thin Playwright wrapper around `core.playwright_base.stealth_context`).
- `scrapers_lib.tier2.dell`: `fetch_dell_product` — stealth browser session
  fetches the product page, then calls Dell's own `csbapi/unifiedpd/techspecs`
  endpoint for each pre-built configuration tile through the same session
  (Akamai cookies ride along). Emits one `ProductSnapshot` per tile with
  ~20 detailed spec categories (processor, display, memory, storage, ports,
  dimensions, wireless, chassis, etc.). Falls back to the tile's six-bullet
  summary when a techspecs response fails, so partial-success tiles still
  ship a valid snapshot.
- `beautifulsoup4>=4.12` dependency for HTML parsing in Tier 2.
- 46 unit tests for `tier2._base`, 47 unit tests for `tier2.dell` (against
  Alienware Aurora 16X + Dell XPS 16 fixtures), 1 gated live integration
  test.
- `docs/ADDING_A_SOURCE.md` — operational guide for adding new Tier 2 fetchers:
  reconnaissance techniques (DevTools Network tab, DOM attribute search,
  framework state blobs, scroll/click probes, bot-protection check), living
  catalog of per-manufacturer acquisition patterns, decision tree, and the
  Dell build captured as a worked case study.
- `scripts/dell/` — re-runnable reconnaissance scripts that captured the
  committed Dell fixtures; referenced from `docs/ADDING_A_SOURCE.md` as the
  template for future-site recon.

### Changed
- `scrapers_lib.core.playwright_base`: `stealth_context` now integrates
  `playwright-stealth` (navigator.webdriver override, chrome-object spoof,
  permissions shim, webgl vendor override, etc.) with a current Chrome-145
  user agent. Wave 1's shallow stealth tripped Akamai on dell.com; the
  upgrade was verified against Alienware + XPS product pages. New kwargs
  on `stealth_context`: `locale` (default `"en-US"`) and `use_stealth`
  (default `True`; opt out for plain persistent-profile contexts).
- `tests/core/test_registry.py` and `tests/core/test_scheduler.py`:
  registry-reset fixtures now snapshot-and-restore instead of wiping, so
  import-time registrations by production modules (e.g. `tier2.dell`) are
  preserved across the test run.

## [0.1.0] — 2026-04-21

### Added
- Initial scaffold: folder structure, `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`, `CHANGELOG.md`, empty module stubs.
- Draft documentation: PRD, Architecture, Tasks, README.
- `scrapers_lib.core.schemas`: Pydantic v2 models — `Anchor`, `AttributionRegex`, `Attribution`, `ProductSnapshot`, `RawMention`.
- `scrapers_lib.core.attribution`: regex gate, URL-map gate, deterministic mention-ID helpers (Reddit post/comment, RSS article, paragraph, YouTube chunk).
- `scrapers_lib.core.logging_config`: opt-in `configure_logging()` helper with per-module level overrides.
- `scrapers_lib.core.registry`: internal fetcher registry with function and decorator (`@register`) forms.
- `scrapers_lib.core.rate_limiter`: per-domain token-bucket `RateLimiter` with pure-logic `Bucket` sub-class.
- `scrapers_lib.core.cache`: `Cache` — diskcache-backed wrapper with per-source TTL defaults from ARCHITECTURE §7.
- `scrapers_lib.core.robots`: `RobotsChecker` — robots.txt-aware URL checker with per-origin caching; injectable `fetch_fn` for testing.
- `scrapers_lib.core.http_client`: `HttpClient` — httpx wrapper with retry/backoff on 429/503/network errors, UA rotation, `Retry-After` respect.
- `scrapers_lib.core.playwright_base`: `BrowserProfile` and `stealth_context` (lazy Playwright import) for per-domain persistent Chromium profiles.
- `scrapers_lib.core.scheduler`: `Scheduler` — SQLite-backed persistent job queue with worker loop, per-job retry, per-domain adaptive backoff, `BlockedError` for explicit 429/403 signals, optional RateLimiter + RobotsChecker integration, callback result delivery, `stats()`, `stop()`.
- Top-level re-exports at `scrapers_lib`: `Anchor`, `Attribution`, `AttributionRegex`, `BlockedError`, `ProductSnapshot`, `RawMention`, `Scheduler`.
- 165 unit tests across `tests/core/` — schemas (28), attribution (27), logging (7), registry (11), rate limiter (15), cache (17), robots (11), http_client (13), playwright_base (15), scheduler (22).

## Versioning

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §14 for the versioning policy. Pre-1.0 releases may change public APIs between minor versions.
