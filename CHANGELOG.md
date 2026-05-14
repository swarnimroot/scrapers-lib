# Changelog

All notable changes to scrapers-lib are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

## [1.6.0] — 2026-05-13

**HP PDP shape dispatcher — STO (`…nr`) fallback + `HPProductNotFoundError` for delisted slugs.** `parse_hp_product_page` now dispatches on `slugInfo.templateKey` + the presence of CTO / STO data blocks rather than assuming every PDP carries CTO tiles. Three shapes are recognized: **(a) CTO customizer URLs** (slugs typically `…av-1`) — unchanged behavior from v1.5 (one snapshot per pre-built "Recommended Configuration" tile, ~23-26 specs each via config-picker + async). **(b) STO SKU-final URLs** (slugs typically `…nr`, e.g. `ap0097nr`, `fa2047nr`) — new path emitting **one** `ProductSnapshot` per URL with `source_id = productInitial.sku` (e.g. `"B96S8UA#ABA"`), specs sourced from the same async `pdpTechSpecs` endpoint (28+ categories on the OMEN 16-ap0097nr reference — strictly more coverage than CTO tiles), prices / rating / review_count / title / image from `productInitial` + `productInitialPrice` + `pdpImages` (first non-`.mp4`/`.webm`/`.mov` URL). **(c) Delisted slugs** (HP silently rewrites discontinued PDP slugs to the shop homepage at the CMS layer — response is 200 but `templateKey="home"` and product surfaces are gone) — raises the new typed `HPProductNotFoundError(RuntimeError)` so consumers can `except HPProductNotFoundError: continue` to skip dead URLs cleanly. Triggered by an external consumer hitting `AttributeError` on `…nr` URLs (the v1.5 chain `.get("pdpCTOConfiguration", {})` did not fire its default because STO PDPs set the value to `None`, not missing) and a different `RuntimeError` on the 17.3" OMEN slug (which turned out to be delisted, not a different DOM template). **Public API additive on top of v1.5.0** — every existing CTO call site behaves identically; STO callers go from crash to working snapshot; consumers gain a typed exception they can catch. Tests: **1147 passed, 22 skipped** (was 1114 / 22 at v1.5.0 — +33 new unit tests; no new gated-live integration tests). No new dependencies.

### Added
- **`scrapers_lib.tier2.hp.HPProductNotFoundError`** — new typed exception derived from `RuntimeError`. Raised when an HP shop PDP slug is delisted or otherwise redirected so the response no longer carries product data (signal: `slugInfo.templateKey != "pdp"`). Module-scoped (not re-exported at the package top level — HP-specific; generalize when a second source needs the same pattern).
- **STO (Stock) PDP fallback path.** New internal helper `_parse_sto_snapshot()` in `tier2/hp.py` emits a single `ProductSnapshot` from `productInitial` (sku, brand, name, family, rating, numReviews, mfpartnumber, product_class) + `productInitialPrice` (regularPrice, salePrice) + `pdpImages.fullImages` (first non-video URL) + async `pdpTechSpecs.technical_specifications` (the same array shape the existing `_flatten_technical_specs` helper already parses). `raw.spec_source = "productInitial+pdpTechSpecs"` (or `"productInitial"` when the async fetch failed).
- **Three small helpers** in `tier2/hp.py`: `_rating_from_product_initial` and `_review_count_from_product_initial` (type-coerce HP's mixed int/string fields, falling back to JSON-LD `aggregateRating`), and `_first_pdp_image_url` (pick the first non-`.mp4`/`.webm`/`.mov` URL from `pdpImages.fullImages`; HP interleaves a marketing video with the still images on STO PDPs, and the sibling `productInitialPrice.images` carries HTML-escaped `&amp;` so `pdpImages.fullImages` is the cleaner source).
- **`scripts/hp/recon_pdp_shapes.py`** — re-runnable reconnaissance probe used to discover the three PDP shapes during Wave 2i. Captures HTML for AV-code customizer, STO `…nr`, and 17.3" outlier URLs, plus a machine-readable cross-URL JSON summary; uses the existing `warmed_curl_session()` helper.
- **Fixtures** under `tests/tier2/fixtures/hp/`: `recon_av_a58a5av1.html` (CTO customizer sanity check), `recon_nr_ap0097nr.html` (STO unit fixture), `recon_nr_ap0097nr_async.json` (STO async-techspecs unit fixture, 28 categories), `recon_av_a7jp9av1_173.html` (homepage-redirect fixture), `recon_pdp_shapes_summary.json` (cross-URL diagnostic summary).

### Changed
- **`parse_hp_product_page`** internal control flow now dispatches on PDP shape (see module docstring). Order: `templateKey != "pdp"` → `HPProductNotFoundError`; CTO configurations present → existing `_parse_cto_tiles()` path (extracted from the inline loop into a named helper, same behavior); `productInitial` populated → new STO snapshot path; neither → opaque `RuntimeError("page structure may have changed")` distinguishing a genuine site redesign from a delisted slug. The v1.5 defensive idiom changed from `.get("pdpCTOConfiguration", {})` to `.get("pdpCTOConfiguration") or {}` because STO PDPs set the value to `None` rather than omitting the key, so the bare-default does not fire.
- **`scrapers_lib.tier2.hp` module docstring** rewritten to describe all three observed PDP shapes (CTO, STO, delisted) with the dispatch signals for each. The shared async `pdpTechSpecs` endpoint behavior is now documented as the spec source for both CTO and STO (it was always called on both — the previous text just framed it as a CTO-specific augmentation).

### Test baseline
- **Unit suite: 1147 passed, 22 skipped** (was 1114 / 22 at v1.5.0). Delta: +33 new unit tests across `TestParseStoFallback` (14), `TestProductNotFoundError` (3), `TestNeitherCtoNorStoRaises` (1), `TestRatingFromProductInitial` (4), `TestReviewCountFromProductInitial` (4), and `TestFirstPdpImageUrl` (6); one existing test in `TestParsePageStructuralFailures` updated to add `templateKey: "pdp"` to its synthetic fixture so it lands in the new "neither CTO nor STO" branch instead of the new `HPProductNotFoundError` branch (preserving its original intent: verify the structural-break path).
- **No new gated-live integration tests.** The HP integration suite at `tests/tier2/test_hp_integration.py` continues to exercise the CTO path; live verification of the STO path was performed during recon (Aurora 16-ap0097nr returned 28 spec categories) and is documented in `scripts/hp/recon_pdp_shapes.py` for re-running.

### Documentation
- `README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md` (§11 HP row + §14 tag list), `docs/CONSUMER_GUIDE.md` (§9 HP row), `docs/SOURCE_ATLAS.md` (§6.2 HP entry), `docs/ADDING_A_SOURCE.md` (§4 HP row), and `docs/TASKS.md` (Current state + new closed Wave 2i entry) updated to describe the three PDP shapes and the new `HPProductNotFoundError` typed exception.

## [1.5.0] — 2026-05-13

**Dell configurator option menu — `include_options` kwarg.** The Dell fetcher can now optionally enrich each emitted `ProductSnapshot` with the product-line's full **hardware-component option menu** (Processor / Graphics / Memory / Storage / Display / Keyboard / Primary Battery / AC Adapter / Operating System / OS Language Pack — 10 modules, ~19 options on the Aurora 16 reference). Off by default; opt in with `fetch_dell_product(url, ..., include_options=True)`. When enabled, the fetcher constructs a `cty/pdp` configurator URL from the shop-landing URL's `spd-slug` and the first tile's order code, navigates to it through the same stealth Playwright session (Akamai cookies stay warm), and parses the SSR'd `.accordion-box.single-column-accordion` modules into the new `ProductSnapshot.options` field. The same options dict is attached to every emitted tile snapshot — the menu is product-line-level, not tile-level. Software / accessories modules (Microsoft 365, antivirus, etc.) live in a different `<input type="radio">` DOM lower on the page and are intentionally not surfaced. **Public API additive on top of v1.4.0** — every existing call site keeps working unchanged. Tests: **1114 passed, 22 skipped** (was 1092 / 21 at v1.4.0 — +22 new unit tests for the configurator parser, URL constructor, and snapshot threading; +1 new gated-live integration test skipped without `SCRAPERSLIB_LIVE_TESTS=1`). No new dependencies.

### Added
- **`scrapers_lib.core.schemas.ComponentOption`** — new Pydantic v2 model with three required fields (`label: str`, `status: str`, `option_id: str`). `status` carries the source site's vocabulary verbatim — Dell uses `"selected"` / `"available"` / `"unavailable"`. Re-exported from `scrapers_lib.__init__`.
- **`ProductSnapshot.options: dict[str, list[ComponentOption]] | None = None`** — new optional field on the existing snapshot schema. Default `None` everywhere; populated only when the Dell fetcher is invoked with `include_options=True`. Other Tier 2 / Tier 3 fetchers continue to emit `options=None`. Field default is `None` rather than `{}` so consumers can distinguish "fetcher did not look" from "fetcher looked and found nothing."
- **`scrapers_lib.tier2.dell.parse_dell_configurator_options(html) -> dict[str, list[ComponentOption]]`** — pure parser for a Dell `cty/pdp` configurator page. Walks every `div.accordion-box.single-column-accordion` (one per hardware module), reads each option card's visible label, `data-option-id`, and `data-status`. Module order in the returned dict mirrors on-page order; option order within each module preserves DOM order. Duplicate `data-option-id` within a module is deduped (first occurrence wins). Returns `{}` for non-configurator pages.
- **`scrapers_lib.tier2.dell._construct_cto_url(shop_url, oc)`** — internal helper that rewrites a shop-landing URL into a `cty/pdp` configurator URL by replacing `/shop/<category-path>/spd/<spd_slug>` with `/shop/cty/pdp/spd/<spd_slug>/<oc>`. Preserves scheme, host, and locale prefix (e.g. `/en-us`, `/en-uk`). Returns `None` for unrecognized URL shapes or empty OC.
- **`scripts/dell/recon_configurator.py`** — re-runnable reconnaissance probe used to discover the `cty/pdp` configurator structure during Wave 2h. Captures pre/post-scroll HTML and an XHR/fetch URL trace; saves under `tests/tier2/fixtures/dell/cto_<oc>_*.html` / `_xhr_urls.txt`. The Wave 2h recon confirmed the 10-module hardware configurator surface is fully present in pre-scroll SSR HTML (no IntersectionObserver hydration needed for the hardware modules), and that no dedicated configurator JSON endpoint is required — DOM parsing is sufficient.
- **`tests/tier2/fixtures/dell/cto_useac16250hbtshtgb_*.html`** + **`cto_useac16250hbtshtgb_xhr_urls.txt`** — fixture set for the Alienware 16 Aurora configurator (`useac16250hbtshtgb` order code).

### Changed
- **`scrapers_lib.tier2.dell.fetch_dell_product`** gained an optional `include_options: bool = False` kwarg. When `True`, the fetcher navigates to the `cty/pdp` URL constructed from the shop-landing URL + the first tile's OC through the same stealth Playwright session, parses the configurator option menu, and attaches the resulting dict to every emitted snapshot's `options` field. Default `False` preserves the historical single-navigation, no-options behavior verbatim — every existing call site sees `s.options is None` exactly as it did at v1.4.0.
- **`scrapers_lib.tier2.dell.parse_dell_product_page`** gained an optional `configurator_options: dict[str, list[ComponentOption]] | None = None` kwarg, threaded to each emitted `ProductSnapshot`'s `options` field. Default `None` preserves the historical pure-parse contract. Symmetric with the existing `techspecs_html_by_oc` kwarg.
- **`scrapers_lib.tier2.dell._fetch_dell_session`** internal return shape changed from `tuple[str, dict[str, str]]` to `tuple[str, dict[str, str], str | None]` — the new third element carries the `cty/pdp` HTML when `include_options=True`, otherwise `None`. Internal helper; not part of the public API.

### Test baseline
- **Unit suite: 1114 passed, 22 skipped** (was 1092 / 21 at v1.4.0). Delta: +22 new unit tests across `TestConstructCtoUrl` (4), `TestParseConfiguratorOptions` (11), `TestParseConfiguratorOptionsEdgeCases` (4), and `TestProductPageWithConfiguratorOptions` (2 + 1 strengthened existing assertion); +1 new gated-live integration test `test_fetch_aurora_live_include_options` in `tests/tier2/test_dell_integration.py`.

### Documentation
- README, `docs/PRD.md`, `docs/ARCHITECTURE.md` (§3 schema, §11 Dell row), `docs/CONSUMER_GUIDE.md`, and `docs/SOURCE_ATLAS.md` should be updated to surface the new `options` field on `ProductSnapshot`, the `include_options` kwarg on `fetch_dell_product`, and the Dell `cty/pdp` configurator surface. **Not done in this commit** — flagged for follow-up so the wave-1 code change can land independently of the docs sweep.

## [1.4.0] — 2026-05-12

**Article fetcher upgraded to Chrome-impersonated, warmed sessions; `warmed_curl_session()` graduated out of Tier 2.** `tier1/article.py` now fetches article HTML via the shared `warmed_curl_session()` helper instead of plain `httpx.get()`. This makes Cloudflare-fronted reviewer sites — notebookcheck.net first, with the broader gaming/tech reviewer set in Demo 3's scope unblocked by the same fix — return real HTML instead of 403. To keep the documented exception contract for callers and the Scheduler's retry / backoff logic, curl_cffi response errors are re-wrapped as `httpx.HTTPStatusError`. `fetch_article`'s signature, return type, and kwargs are unchanged. The helper itself moved from `scrapers_lib.tier2.base` to a new shared module `scrapers_lib.core.curl_session`; `tier2.base` keeps a re-export so HP / MSI / BestBuy callers stay byte-for-byte unchanged. No new dependencies (`curl_cffi>=0.7` already shipped in Wave 2c). Tests: **1092 passed, 21 skipped** (was 1073 / 20 at v1.3.0 and 1082 / 20 at v1.3.1 — +10 new article-fetcher / homepage-derivation unit tests, +1 new live integration test skipped without `SCRAPERSLIB_LIVE_TESTS=1`).

### Added
- **`scrapers_lib.core.curl_session`** — new shared module housing `warmed_curl_session()`. Identical signature and semantics to the v1.3.1 helper that previously lived in `tier2/base.py`; the helper is now reused by the Tier 1 article fetcher in addition to the three Akamai-gated Tier 2 / Tier 3 callers.
- **Notebookcheck added as a Tier 1 RSS source** via the existing `rss` fetcher. Firehose feed URL: `https://www.notebookcheck.net/RSS-Feed-All-Articles-EN.165552.0.html` (500-entry English-edition mix of news + reviews). No code change in the library — the RSS path worked as-is; follow-up `article` fetches now also clear notebookcheck's Cloudflare gate via the upgraded fetcher above. Reconnaissance also identified two narrower feeds (`/News.152.100.html` for news-only, `/RSS-Feed-Notebook-Reviews.8156.0.html` for reviews-only) for consumers that want category-routed ingestion without parsing `<category>` tags on the firehose.

### Changed
- **`tier1/article.py` `_fetch_html`** swapped from `httpx.get()` to `warmed_curl_session()` (Chrome TLS impersonation, HTTP/1.1, per-host homepage warming). The existing `Accept` and `Accept-Language` headers and the existing `_DEFAULT_USER_AGENT` continue to ride on the target request. `curl_cffi` response errors on the main fetch are translated into `httpx.HTTPStatusError` so the documented exception contract — and the Scheduler's retry / backoff logic that depends on it — keep working. `fetch_article`'s public signature, return type, and kwargs are unchanged.
- **`scrapers_lib.tier2.base.warmed_curl_session`** is now a re-export of `scrapers_lib.core.curl_session.warmed_curl_session`. Existing `from scrapers_lib.tier2.base import warmed_curl_session` imports keep working unchanged; no caller-side edits in `tier2/hp.py`, `tier2/msi.py`, or `tier3/bestbuy.py`.

### Test baseline
- **`tests/tier2/test_base.py::TestWarmedCurlSession` moved to `tests/core/test_curl_session.py`** to track the helper's new home.
- **`tests/tier1/test_article.py`** gains a `fake_curl_cffi` module fixture mirroring the pattern established in `tests/tier2/test_base.py`, so the article fetcher's curl_cffi integration is unit-tested without network.
- One new opt-in live integration test against notebookcheck.net, gated by the existing `SCRAPERSLIB_LIVE_TESTS=1` env var (mirrors the IGN live test in `tests/tier1/test_article_integration.py`).

### Documentation
- `README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/CONSUMER_GUIDE.md`, `docs/SOURCE_ATLAS.md`, `docs/TASKS.md`, and `docs/ADDING_A_SOURCE.md` updated to reflect the helper's new home, the article fetcher's upgraded acquisition method, and notebookcheck's presence in the supported-feed catalog.

## [1.3.1] — 2026-05-07

**Wave 2g — `warmed_curl_session()` helper graduated into `tier2/base`.**
Pure refactor — public API unchanged. Three modules
(`tier2/hp.py`, `tier2/msi.py`, `tier3/bestbuy.py`) had each been
duplicating the same warm `curl_cffi` + Chrome TLS impersonation +
HTTP/1.1 + homepage-warming bootstrap dance to clear the Akamai HTTP/2
RST-stream gate. Wave 2g extracts that primitive into a shared
context-manager helper so future Akamai- / CDN-gated Tier 2 / Tier 3
sources can drop in without re-implementing the warming sequence.
Tests: **1082 passed, 20 skipped** (was 1073 / 20 pre-wave — +9 new
unit tests for `warmed_curl_session`). No new dependencies.

### Added
- **`scrapers_lib.tier2.base.warmed_curl_session(homepage, *, impersonate="chrome", warm=True, warm_delay=1.0, warm_headers=None, timeout=30.0)`**
  — context manager yielding a warmed `curl_cffi.requests.Session`
  configured with Chrome TLS impersonation and `CurlHttpVersion.V1_1`.
  When `warm=True`, fires a homepage GET and sleeps `warm_delay`
  seconds before yielding so cookies settle. Warm-up failures are
  swallowed and logged at DEBUG. `curl_cffi` is imported lazily inside
  the helper so callers of unrelated `tier2.base` symbols
  (`parse_product_jsonld`, `parse_spec_table`, etc.) do not pay the
  `curl_cffi` import cost. The `warm_headers` kwarg ships unused by
  current callers but is there for future Akamai-gated sources whose
  warm-up needs custom headers.

### Changed
- **`tier2/hp.py` `_fetch_pdp_with_techspecs`** now opens its session
  via `warmed_curl_session(HOME_URL, impersonate=..., warm=...)` instead
  of constructing the `curl_cffi` Session inline. Caller-side headers
  on the main PDP GET (`Accept`, `Accept-Language`) and the follow-up
  `_fetch_async_techspecs(s, ...)` call are unchanged.
- **`tier2/msi.py` `_fetch_msi_html`** now opens its session via
  `warmed_curl_session(HOME_URL, impersonate=..., warm=...)`. The main
  `s.get(url, ...)` call's caller-side headers (`Accept`,
  `Accept-Language`, **`Referer`**) are unchanged — Referer stays on
  the target request, not on the warm-up.
- **`tier3/bestbuy.py` `_fetch_pdp` and `_iter_reviews_pages`** both
  now open their sessions via
  `warmed_curl_session(HOME_URL, impersonate=..., warm=...)`. No
  caller-side headers on the main GETs (unchanged).
- **DEBUG warm-failure log text** unified across all three modules
  from per-module prefixes (`"hp: warm failed: ..."`, `"msi: warm
  failed: ..."`, `"bestbuy: warm failed: ..."`) to a single
  `"warmed_curl_session(<homepage>): warm failed: ..."`. INFO and
  WARN log lines elsewhere in the modules are unchanged.
- **Public API unchanged.** `fetch_hp_product`, `fetch_msi_product`,
  and `fetch_bestbuy_reviews` all preserve their `warm: bool = True`
  and `impersonate: str = "chrome"` kwargs verbatim. Observable behavior
  unchanged. Existing tests (e.g.
  `test_target_request_carries_referer_and_accept` in
  `tests/tier2/test_msi.py`) pass without modification.

### Test baseline
- **Unit suite: 1082 passed, 20 skipped** — was 1073 / 20 pre-wave;
  the +9 delta is `tests/tier2/test_base.py::TestWarmedCurlSession`.
- No live integration tests added in Wave 2g (helper is exercised
  through the existing HP / MSI / BestBuy gated-live paths).

### Documentation
- **v1.3.0-state alignment audit** across `README.md`, `docs/PRD.md`,
  `docs/ARCHITECTURE.md`, and `docs/CONSUMER_GUIDE.md` (commit `5c3073f`,
  recorded under `[Unreleased]` in commit `a9eb574` and folded into
  this 1.3.1 entry post-tag). `ARCHITECTURE.md`: fixed broken §5.1
  Quickstart (`rss.fetch_feed` → `rss.fetch_rss_feed`); marked
  `RawMention.attribution` Optional in §3.3 to match the discovery-mode
  contract; dropped the misleading "PRAW-compatible signatures so OAuth
  can swap in later" claim from the §11 Reddit row (Reddit's Nov-2025
  self-service block is indefinite); rewrote the §12.1 `register_fetcher`
  paragraph (it read as "not built in v0.1" while §12.2 step 3 calls it
  directly); extended the §14 release-tag example list through v1.3.0;
  dropped the stale "in v0.x" qualifier from the §16 no-PyPI bullet;
  added `asus_www.py` and `_version.py` to the §1 file tree; switched
  the §2 Tier 1 example from "Reddit (PRAW)" to "Reddit (unauthenticated
  JSON)". `README.md`: tagged the BestBuy Developer API credentials
  row as dormant (self-service approvals not currently flowing);
  shifted the Reddit row's "supported way in v1.0" to "since v1.0".
  `PRD.md`: §5 non-goals and §7 in-scope language now reflect the
  actual `httpx` + `curl_cffi` (warmed-session) + selective stealth
  Playwright primitive mix (Playwright is Dell-only at v1.3.0); §8
  notes that the v1.0.0 freeze has held through v1.3.0 across Waves
  2d/2e/2f. `CONSUMER_GUIDE.md`: Targets header v1.1.0+ → v1.3.0+;
  §5 worker-entry-point example now imports the full v1.3 six-brand
  Tier 2 set (added `acer` and `msi`).
- **Post-Wave-2g doc sweep + library-intrinsic roadmap pivot.**
  Bumped headline version stamps to v1.3.1 across `README.md`,
  `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/CONSUMER_GUIDE.md`,
  and `docs/SOURCE_ATLAS.md`; extended `PRD.md` §4 + §8 and
  `ARCHITECTURE.md` §11 + §14 to include Wave 2g (`warmed_curl_session()`
  graduation) in the freeze-held wave list and tag-list example.
  `docs/TASKS.md` rewritten more substantially: closed-wave entry
  added for Wave 2g; the `Current consumer drivers` section renamed
  to `Downstream consumers (external)` and reframed in past tense
  to acknowledge Demo 2 / Demo 3 / Pilot 1 as out-of-tree consumer
  projects that no longer drive this library's roadmap; new
  `Library-intrinsic next directions` section surfaces plugin /
  extension API, PyPI publication, and a deferred-until-driven
  source catalog as candidate next directions without locking one;
  Deferred section trimmed accordingly.

## [1.3.0] — 2026-05-07

**Wave 2f — Tier 2 expansion: Acer + MSI greenfield fetchers.** Two
new manufacturer modules complete the six-brand Tier 2 set that
Demo 2's `Competitor Columns` 83-row spec schema needs (Dell + HP +
Lenovo + ASUS-rog + ASUS-www + **Acer + MSI**). Acer's `acer.com`
PDP is plain-httpx-reachable (13 SSR `<table class="agw-table_techSpec">`
blocks per `/pdp/<SKU>` URL, no anti-bot, ~60+ unique label keys per
page, per-SKU granularity). MSI's `us.msi.com` is Akamai-gated and
uses the `curl_cffi` + Chrome impersonation + warmed-session primitive
established by HP and BestBuy in earlier waves to fetch
`/Laptop/<slug>/Specification` (column-per-SKU `<table>`, 27-31
spec rows universal across gaming + premium AI/Stealth lines, one
snapshot per `<thead>` SKU column). Both registered fetchers (`acer`,
`msi`) are additive on top of the frozen v1.0 public API — no signature
changes elsewhere. Tests: **1073 passed, 20 skipped** (was 909 / 20
pre-wave — +164 new unit tests across acer +57 and msi +107). No new
dependencies — `curl_cffi>=0.7` (used by MSI) already shipped in Wave 2c.

### Added
- **`tier2/acer.py` `fetch_acer_product`** (`@register("acer")` →
  `list[ProductSnapshot]`). Fetches `acer.com/<region-locale>/<brand>/
  laptops/<model>/pdp/<SKU>` (the `/pdp/<SKU>` suffix is required —
  bare model URLs return a model-overview page that lists SKUs but
  doesn't carry specs); parses 13 SSR `<table class="agw-table agw-table_techSpec">`
  blocks via `tier2.base.parse_spec_table()` into a flat `specs` dict
  (typically 60+ unique label keys across Operating System / Processor
  / Graphics / Memory / Storage / Display / Battery / I/O / Wireless /
  Camera / Keyboard / Touchpad / Audio / Dimensions / Weight / Security
  / Sensors categories; set varies per SKU — detachables add a
  "Tablet Mode" row absent on clamshells). JSON-LD Product enriches
  `title` / `brand` / `image_url` / `price` / `currency` /
  `availability_text`. Plain `httpx.get()` with Chrome UA returns 200
  OK; no anti-bot, no warming. Per-SKU granularity (each URL targets
  exactly one SKU). `raw.spec_source` = `"ssr_table"`. The
  `agw-table_techSpec` class looks like a CSS-module hash but is
  stable across all probed regions and product lines. 57 unit tests
  in `tests/tier2/test_acer.py` against Aspire 7 Intel + Predator
  Helios Neo 16s AI + Nitro V 16s AI fixtures.

- **`tier2/msi.py` `fetch_msi_product`** (`@register("msi")` →
  `list[ProductSnapshot]`). Fetches `us.msi.com/Laptop/<slug>` and
  `us.msi.com/Laptop/<slug>/Specification` via `curl_cffi` with
  Chrome TLS impersonation + warmed session (visit `https://us.msi.com/`
  first, brief sleep, then PDP) — the Akamai HTTP-layer gate on plain
  `httpx` returns 403; the warmed `curl_cffi` primitive (same one used
  by HP and BestBuy) clears it. **`/Specification` is universal across
  MSI's product lines** (gaming Raider / Crosshair + premium Stealth-AI),
  hosting a single `<table>` with **column-per-SKU** layout: `thead`
  row of SKU column headers + `tbody` rows pairing `<th>` label with
  `<td>` per SKU column, 27-31 spec rows per page covering Operating
  System / Processor / Graphics / Display / Memory / Storage / I/O
  Ports / Webcam / Audio / Keyboard / Battery / AC Adapter / Wireless
  LAN / Bluetooth / Security / Dimensions / Weight / Bag / Mouse (set
  varies by line). One snapshot per `<thead>` SKU column. Bare
  `/Laptop/<slug>` URLs fetch `/Specification` first (comprehensive);
  on parse failure they fall back to the main page's JSON-LD `ItemList`
  (~11-field highlights summary on newer AI/Stealth product lines only).
  Explicit `/Specification` URLs skip the fallthrough. New optional
  `warm: bool = True` and `impersonate: str = "chrome"` kwargs on
  `fetch_msi_product` (mirroring HP's Wave 2e additions). `raw.spec_source`
  = `"specification_table"` (primary) or `"jsonld_itemlist"` (fallback).
  No new deps — `curl_cffi>=0.7` already shipped in Wave 2c. 107 unit
  tests in `tests/tier2/test_msi.py` against Stealth 16 AI+ B3WX
  (main + spec) + Raider 16 Max HX B2WX (main + spec) + Crosshair 16
  HX E14WX (spec) fixtures.

  **Recon revision noted for the historical record:** initial recon
  read Stealth-AI's main page as having only the JSON-LD `ItemList`
  surface and treated `/Specification` as gaming-only. That was wrong
  — `/Specification` is universal; the ItemList is supplementary, not
  a substitute. The fetcher's locked default behavior reflects the
  corrected reading: `/Specification`-first with ItemList fallback,
  no `prefer_specification` kwarg.

- **`scripts/msi/fetch_fixtures.py`** — re-runnable MSI fixture refresh
  probe. Warms a `curl_cffi` + Chrome + HTTP/1.1 session on the
  `us.msi.com` homepage, then fetches both main-page and `/Specification`
  surfaces for the three reference models above and saves them under
  `tests/tier2/fixtures/msi/`.

- **`docs/ARCHITECTURE.md` §11** — Acer + MSI per-source coverage rows
  added (replacing the prior `Acer, MSI: Deferred (post-demo)` row).

- **`docs/ADDING_A_SOURCE.md` §4** — Acer + MSI per-manufacturer
  acquisition pattern entries added (replacing the prior deferred row).

## [1.2.1] — 2026-05-07

### Added
- **`tier1/reddit.py` `fetch_reddit_comments` gained an `emit_all_comments`
  kwarg.** Default `False` (existing behavior: per-comment regex match
  filters off-topic comments at fetch time). When `True`, **comments**
  bypass the regex match and emit unfiltered with `attribution=None`,
  letting the caller inherit attribution from the parent post via
  `RawMention.parent_id` (Reddit `link_id`). The post emission still
  fans out per matched anchor as before. Useful when downstream has a
  stronger attribution signal than per-comment text matching (e.g. a
  primary-attributed parent post in a corpus DB) — Demo 3 (Reddit
  sentiment) needs full thread carryover. Additive, non-breaking.

## [1.2.0] — 2026-05-07

**Wave 2e — Tier 2 expansion: HP coverage fix + ASUS www non-ROG
fetcher.** HP's `tier2/hp.py` now hydrates Tech Specs from a sibling
GraphQL endpoint on the same warmed `curl_cffi` session that fetches
the PDP, doubling per-tile coverage from ~12 to ~23-26 categories
including Dimensions / Weight / I/O Ports / Audio Features / Power
supply / Warranty (set varies by product family). ASUS gained a
sibling parser at `tier2/asus_www.py` for `www.asus.com` Zenbook /
Vivobook / TUF Gaming product lines via Nuxt JS-state evaluation
(`py_mini_racer` in-process V8) — the same HP-gap axes are present
on every product family. Lenovo URL-acceptance recon resolved as NO
(consumer `lenovo.com/p/...` PDPs carry no PSREF link); the existing
PSREF-only constraint stays as-is, search-bridge resolver deferred.
Public API frozen — every change additive on top of v1.1.0. Tests:
904 pass / 20 skipped (v1.1.0 was 832 / 19 — 72 new unit tests
across HP +17, ASUS www +60, asus URL regex +6, ASUS host dispatch
+4, and a few small ones; +1 gated live integration test). One new
dep: `py_mini_racer>=0.6` (free, open-source, in-process V8 ~5 MB
win_amd64 wheel) — only the ASUS www parser uses it; lazily imported
so consumers that never touch ASUS don't pay the V8 startup cost.

### Added
- **ASUS fetcher extended to `www.asus.com` non-ROG product lines** (Wave
  2e step 4). New module `tier2/asus_www.py` covers Zenbook, Vivobook,
  and TUF Gaming spec pages at
  `www.asus.com/<region>/laptops/for-{home,gaming}/<line>/<model>/techspec/`.
  The rendered DOM only paginates 1-2 SKU columns at a time, so the
  parser instead extracts the Nuxt SSR state from a
  `window.__NUXT__=(function(...){...}(...))` IIFE: locate via
  `(?:window\.)?__NUXT__\s*=\s*\(function\(`, paren-balance to extract
  the full ~200 KB expression, evaluate via `py_mini_racer` (in-process
  V8), then read `state.PDPage.PDTechSpecM2.SpecList` — typically
  22-28 categories per page (28 on Zenbook/Vivobook, 22 on TUF). Each
  Content cell HTML-decodes and br-splits to multi-SKU rows
  (handles `<br>`, `<BR>`, and `</br>` sic on Vivobook), then dedupes
  in first-occurrence order. **All HP-gap axes (Dimensions / Weight /
  I/O Ports / Audio) consistently present across all three product
  lines** — closes the second of two Wave 2e coverage targets after
  the HP step. Plain `httpx` is sufficient (no DataDome on
  `www.asus.com`, unlike `shop.asus.com`). **Public API unchanged**:
  the existing `fetch_asus_product` registered fetcher routes
  `www.asus.com` URLs to the new module via host dispatch in
  `tier2/asus.py`; same `SOURCE = "asus"` so a single Anchor with
  `source_urls={"asus": <url>}` works against either surface.
  `raw.spec_source` = `"www_asus_pd_techspec_m2"` marks www-sourced
  snapshots (vs `"rog_spec_page"` for ROG). 60 new unit tests +
  1 gated live integration test added.

  **New dep:** `py_mini_racer>=0.6` (free, open-source, in-process V8 ~5
  MB win_amd64 wheel; no Node subprocess, no startup overhead beyond
  the V8 isolate creation per fetch).

- **`tier3/bestbuy.py` accepts modern PDP URL forms.** BestBuy migrated
  away from the legacy ``/site/<slug>/<7-digit-SKU>.p`` form to two new
  shapes: ``/product/<slug>/<MODEL_ID>/sku/<7-digit-SKU>`` (SKU still
  in path) and ``/product/<slug>/<MODEL_ID>`` (model-id-only, no SKU
  anywhere in the URL). `_extract_sku` now tries both legacy + modern
  path regexes, then `?skuId=<SKU>` query, then — as a last resort —
  reads `"skuId":"<SKU>"` from the PDP's always-present
  ``<meta name="analytics-metadata">`` block (works against both the
  HTML-escaped attribute form and any unescaped occurrence). The
  default `paginate=False` path already had the PDP HTML in hand and
  passes it through; the `paginate=True` path tries the URL first
  and only fetches the PDP for the HTML fallback when the URL has no
  SKU. `_extract_sku` gained an optional `html: str | None = None`
  kwarg; signature change is backward-compatible.

- **`docs/SOURCE_ATLAS.md`** — 2-minute visual map of how each source
  is scraped, why that method, what it returns, and one realistic
  example per source. Complements `CONSUMER_GUIDE.md` (recipes),
  `ARCHITECTURE.md` §11 (dense field tables), and `ADDING_A_SOURCE.md`
  (recon methodology). Linked from README Documentation section.

### Changed
- **HP fetcher coverage expanded from ~12 to ~23-26 spec categories per
  tile** (Wave 2e step 2). `tier2/hp.py` now makes two HTTP calls on a
  single warmed `curl_cffi` + Chrome + HTTP/1.1 session: the existing
  PDP HTML for the config-picker tiles, plus a sibling slug-keyed
  GraphQL endpoint at
  `/us-en/shop/app/api/web/graphql/page/pdp%2F<slug>/async` for the
  product-wide Tech Specs section (Dimensions, Weight, External I/O
  Ports, Audio Features, Network interface, Battery Recharge Time,
  Power supply, Webcam, Warranty, etc. — set varies by product family).
  Both arrays use the same row shape and are flattened uniformly;
  per-tile (config-picker) values overlay async (product-wide) values
  on overlap. The async fetch is best-effort — on any failure (non-200,
  JSON parse error, missing envelope) the fetcher logs at INFO and
  falls back to config-picker-only data, exactly mirroring the v1.1
  12-category behavior. **Public API unchanged** — same
  `fetch_hp_product` entry point, same `ProductSnapshot` output shape;
  consumers see more keys in `specs` and a richer `config_summary`.
  New optional `warm` and `impersonate` kwargs on `fetch_hp_product`.
  New optional `async_techspecs` kwarg on `parse_hp_product_page` for
  testability. New `raw.spec_source` value
  `"pdpCTOConfiguration+pdpTechSpecs"` (vs `"pdpCTOConfiguration"`)
  marks merged snapshots. The `httpx` import was dropped from the HP
  module (`curl_cffi` is now the sole HTTP primitive there); `httpx`
  remains a library dep for other fetchers. No new deps —
  `curl_cffi>=0.7` already shipped in Wave 2c.

### Fixed
- **`tier2/asus` URL regex accepts region/locale prefixes.**
  `_PRODUCT_PATH_RE` previously required `/laptops/` as the very first
  path segment, rejecting every canonical asus.com URL — ASUS always
  serves through region-prefixed paths (`/us/laptops/...`,
  `/me-en/laptops/...`, `/sa-en/laptops/...`, `/uk/laptops/...`, ...).
  The regex now accepts an optional locale segment (2-3 letter country
  optionally followed by a hyphen + 2-4 letter language) before
  `/laptops/`, and continues to accept the region-less form (which
  asus.com 302-redirects to a regional URL). `_source_id_from_url`
  needed no change because it splits from the right. 6 new unit tests
  in `TestSourceIdFromUrl` cover both region-prefixed valid forms and
  region-prefixed negative cases (motherboards path / series-only
  index still rejected).
- **Registered-fetcher count corrected from 14 to 13** across
  `README.md`, `CONSUMER_GUIDE.md` (§1 intro + §9 data-shape table),
  `PRD.md` §4, and prior `[1.0.0]` changelog entries. Runtime
  `list_fetchers()` enumerates exactly 13 names. The "14th" was a
  phantom `bestbuy` alias documented in `CONSUMER_GUIDE.md` §9 and
  the README Tier 3 key list — `tier3/bestbuy.py` defines the
  `SOURCE = "bestbuy"` constant but never calls `@register(SOURCE)`
  on it, so no such fetcher was ever reachable via the registry.
  Docs now match code; the `SOURCE` constant is left in place as
  dead (harmless) code for future cleanup.

## [1.1.0] — 2026-04-22

**First additive release on the frozen v1.0 public API.** Wave 2d
extends BestBuy reviews coverage without changing any existing
fetcher signature. `paginate=True` is a new keyword on
`fetch_bestbuy_reviews`; default behavior is verbatim unchanged from
v1.0.0. Tests: 809 unit pass / 17 skipped (v1.0.0 was 762 / 16 — 47
new unit tests, 1 new gated live integration test). Gated live
integration green against SKU 6628371 (Alienware Area-51 18"):
default path ~5 reviews, paginate path 40 reviews across 2 pages,
all with `published_at` populated.

### Added
- **`fetch_bestbuy_reviews` paginate mode.** New kwargs
  `paginate: bool = False` (default preserves v1.0 PDP-inline
  behavior), `max_pages: int | None = None`, and
  `page_delay_seconds: float = 3.0`. With `paginate=True` the fetcher
  walks `bestbuy.com/site/reviews/name/<SKU>?page=N` (20 reviews per
  page) via the same curl_cffi + Chrome impersonation + HTTP/1.1
  primitive that Wave 2c established for the PDP. Terminates when a
  page has zero `<li class="review-item">` containers or when the
  `<link rel="next">` tag drops out. Attribution is resolved once
  against the caller-supplied PDP URL and reused for every review
  across all pages.
- **`parse_bestbuy_reviews_page` pure-parse function** — one
  reviews-page HTML → list of `RawMention`. Walks each
  `<li class="review-item">` container, extracts the embedded
  `<script type="application/ld+json">` `@type: Review` block for
  body / title / author / rating, and the per-review
  `<time class="submission-date" title="Mon DD, YYYY H:MM AM/PM">`
  element for `published_at`.
- **`published_at`** on paginated reviews. UTC-aware; stored as
  UTC-naive-promoted-to-UTC because BestBuy's `<time title>` strings
  carry no timezone info.
- **New `raw` fields** on paginated reviews: `verified_purchase`
  (bool), `helpful_count` (int parsed from the helpfulness-button
  aria-label), `ownership_duration` (e.g. "2 weeks", "6 months"
  parsed from the "Owned for X when reviewed" phrase).
- **Recon probe** `scripts/bestbuy/probe_reviews_pagination.py` +
  three captured fixtures (`tests/tier3/fixtures/bestbuy/
  reviews_6628371_page1..3.html`) — mirrors the Wave 2c
  `probe_posture.py` discipline and documents pagination mechanics
  for future maintenance.

### Changed
- **`docs/ARCHITECTURE.md` §11 BestBuy-reviews row** updated to
  document both modes (default / paginate), the full list of
  populated fields, and the new caveat that BestBuy omits timezone
  from timestamps. Also corrects a pre-Wave-2d assumption: the
  earlier note implying JSON-LD on the reviews-surface carried
  `datePublished` was wrong — dates are in the DOM on both surfaces.
  Wave 2d recon discovered this before code was written.
- **Module docstring** (`tier3/bestbuy.py`) rewritten to cover both
  modes explicitly.

### Memory
- `project_wave4_closed_v100.md` remains current; Wave 2d completion
  documented via new `project_wave2d_closed_v110.md` (see
  `MEMORY.md` index).

## [1.0.0] — 2026-04-22

**v1.0.0 freezes the public API.** From this release forward, schemas and
public fetcher signatures are stable; backward-incompatible changes
require a major bump, and removed public APIs go through a one-minor-
version deprecation warning before removal. No fetchers added in this
wave — the wave is purely the stability sweep that completes the 1.0
contract.

### Changed
- **`scrapers_lib.tier2._base` → `scrapers_lib.tier2.base`** (breaking).
  The module was underscore-prefixed (signaling "internal") but is in
  fact the documented extension surface for building new Tier 2
  fetchers — five public helpers (`parse_product_jsonld`,
  `parse_inline_json`, `parse_spec_table`, `normalize_spec_value`,
  `fetch_rendered_html`), a dedicated test file, and a full section in
  `docs/ADDING_A_SOURCE.md`. Renamed at the v1.0 boundary so it carries
  no underscore into the frozen surface. All in-tree importers updated
  (5 Tier 2 fetchers, 3 Tier 3 / Tier 1 cross-importers, the unit test
  file, 6 `scripts/` recon probes, `docs/ADDING_A_SOURCE.md`,
  `docs/TASKS.md`, 3 `scripts/*/README.md` headings). `CHANGELOG.md`
  historical entries for v0.2.0 / v0.3.0 still reference the original
  `_base` name — accurate to what shipped at those releases.
- **Library version is single-sourced from `scrapers_lib/_version.py`.**
  Previously the version appeared in both `scrapers_lib/__init__.py`
  (as `__version__`) and `pyproject.toml` (as `version`); four Tier 1
  / core modules additionally hardcoded stale copies inside User-Agent
  strings (`robots.py` still said `0.1`, `bestbuy_api.py` said `0.4`,
  `article.py` / `rss.py` / `reddit.py` said `0.5`). Now: one
  `__version__` in `_version.py`, `__init__.py` re-exports it,
  `pyproject.toml` reads it via `[tool.hatch.version]`, and all five
  UA sites derive it via f-string. Future releases bump one place.
- **`pyproject.toml` `Development Status` classifier** flipped from
  `2 - Pre-Alpha` to `5 - Production/Stable`.
- **`docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md`, `README.md`**
  status headers flipped from `draft` to `stable`; all "(subject to
  revision)" qualifiers and the ARCHITECTURE draft-stage callout
  removed. PRD §4 success criteria rewritten in past tense (all met
  at v1.0.0); PRD §8 and ARCHITECTURE §14 versioning sections
  rewritten to reflect post-freeze posture.
- **README**: new "Public API" section between "Repository layout" and
  "Documentation" — documents the top-level re-exports, per-module
  deep-import cheat sheet, and the fetcher signature + registry-key
  table (13 registered fetchers across the three tiers).

### Fixed
- **README Quickstart example** called `rss.fetch_feed(...)`; the real
  registered name is `fetch_rss_feed`. Fixed.
- **README credentials table** listed a Reddit row requiring
  `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT`
  via PRAW — stale since Wave 3 dropped PRAW for unauthenticated
  JSON (per `project_reddit_api_blocked`). Row rewritten to reflect
  the unauthenticated posture.

### Removed
- **`scrapers_lib/tier2/acer.py`** and **`scrapers_lib/tier2/msi.py`**
  (breaking — empty 1-line scaffolds; docstrings incorrectly claimed
  "implemented in Wave 2a"). Acer and MSI remain in scope for later
  minor versions per `docs/TASKS.md` Wave 2b; the modules will return
  when real fetchers are built. Corresponding `"acer"` and `"msi"`
  entries in `scrapers_lib.core.cache.DEFAULT_TTLS` removed.

### Test baseline
- **Unit suite: 762 passed, 16 skipped** — unchanged from v0.5.0
  (no regressions from the API-stability sweep).
- Integration suite (`SCRAPERSLIB_LIVE_TESTS=1 pytest`) run live
  pre-tag against all 13 registered fetchers. The BestBuy Developer
  API integration is the one expected skip until `BESTBUY_API_KEY`
  lands in `.env` (~2026-04-29 per registration date); all other
  gated-live tests verified green at the v1.0.0 boundary.

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
