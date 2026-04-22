# Changelog

All notable changes to scrapers-lib are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

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
