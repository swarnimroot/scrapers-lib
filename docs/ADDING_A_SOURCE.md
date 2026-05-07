# Adding a Tier 2 source

**Status:** active &nbsp;·&nbsp; **Last updated:** 2026-04-22 &nbsp;·&nbsp; **Applies to:** library version ≥ 0.2.0

Operational guide for adding a new Tier 2 fetcher (manufacturer spec pages: HP,
Lenovo, ASUS, Acer, MSI — and future additions). Read this *before* touching
code. The Dell implementation in v0.2.0 is the first worked example; its full
discovery story is in §7.

---

## 1. Why this doc exists

Tier 2 sources (manufacturer spec pages, retail product pages) each expose
specs through a *different* mechanism. An internal API on one site, a dedicated
spec-sheet subdomain on another, server-rendered tables on a third. You cannot
predict the mechanism from reading the shop page.

If you skip reconnaissance and dive into coding, you will ship either a
**shallow** scraper (six marketing bullets instead of twenty detailed
categories — real risk: we nearly did this with Dell) or a **brittle** scraper
(page DOM changed, selectors rot). Either way, wasted work.

This doc captures: the reconnaissance techniques, the acquisition patterns
already known, and a decision tree for picking the right pattern.

## 2. The golden rule

**Do reconnaissance before writing any fetcher code.** Every site is different.

**Do not assume the previous site's pattern applies.** Dell uses an internal
API behind Akamai. Lenovo probably uses PSREF (a dedicated spec-reference site
on a separate domain, no Akamai). HP / ASUS / Acer / MSI are all unknowns.
Inheriting Dell's approach on a different vendor is a category error waiting to
happen.

## 3. Reconnaissance techniques

The goal of reconnaissance is to answer three questions:

1. Where does the manufacturer's own UI fetch the spec data from?
2. Is there anti-bot protection we need to defeat first?
3. Does the pattern generalize across multiple products on the same site?

Techniques below, ordered from cheapest to most elaborate.

### 3.1. Chrome DevTools → Network tab (fastest human method)

1. Open the product page in Chrome.
2. Press F12 to open DevTools.
3. Go to the **Network** tab, filter to **Fetch/XHR**.
4. Click the UI element that reveals specs ("Tech Specs" button on Dell; might
   be a tab, accordion, or modal elsewhere).
5. Watch for a new request to appear. Right-click → **Copy** → **Copy URL**.
   That is the endpoint.

If nothing fires when you click, specs are either already in the page (§3.4)
or loaded on scroll (§3.6).

### 3.2. Programmatic DOM attribute search

Same information, scripted. After fetching the page HTML (with stealth if
needed), search every element attribute — not just class or id — for the
feature keyword:

```python
import re
# Find every attribute value containing "spec"
for m in re.finditer(r'[a-z_-]+="([^"]*spec[^"]*)"', html, re.I):
    print(m.group(0))
```

This is literally how the Dell `data-url="/csbapi/unifiedpd/techspecs/..."`
endpoint was discovered. See `scripts/dell/inspect_fixture.py` for the
worked example.

### 3.3. Schema.org JSON-LD

Look for `<script type="application/ld+json">`. Most manufacturers embed a
schema.org `Product` object with brand, name, image, aggregateRating, and an
offer (price, availability). Consistent across many sites. Good for
**enrichment** — rarely carries the full spec sheet, but gives us shared
metadata for free.

Parser: `scrapers_lib.tier2.base.parse_product_jsonld`.

### 3.4. SSR'd spec tables in the product page

If the raw HTML (`Ctrl+U` view-source, not the rendered DevTools Elements tab)
already contains the spec table, parse it directly. Two common shapes:

- `<table>` with `<tr><th>Label</th><td>Value</td></tr>` rows.
- `<dl>` with `<dt>Label</dt><dd>Value</dd>` pairs.

Parser: `scrapers_lib.tier2.base.parse_spec_table`. It handles both shapes
and takes an optional `container_selector` when a page has multiple unrelated
tables.

### 3.5. Framework state blobs

Modern SPAs frequently ship their page model as JSON in a top-level script.
The most common:

- `<script id="__NEXT_DATA__" type="application/json">{...}</script>` — Next.js.
- `window.__INITIAL_STATE__ = {...};` — various Redux / Vuex apps.
- `window.__APOLLO_STATE__ = {...};` — Apollo Client.
- `window.__PRELOADED_STATE__ = {...};` — some older SSR setups.

When present, these are the cleanest source of structured product data. Parser:
`scrapers_lib.tier2.base.parse_inline_json`.

### 3.6. Scroll + wait probe

If specs are not in the initial DOM, scroll the page in increments and watch
whether `document.body.scrollHeight` keeps growing or whether a specific
selector fills in. Common pattern for below-the-fold sections that use
`IntersectionObserver` lazy-loaders.

Worked example: `scripts/dell/recon.py`. (For Dell this probe came back
negative — the detailed specs were *not* scroll-hydrated. But the technique
would have been the answer on a different site.)

### 3.7. Click + observe probe

If specs hide behind a "View details" / modal / expander, open Playwright
DevTools (or watch the Network tab while running headed), click the trigger,
and watch what fires *or* whether the DOM grows in place.

### 3.8. Bot-protection check

Start with `httpx.get(url, headers={"User-Agent": "<current-Chrome-UA>"})`.

- Returns 200 with real HTML → no (or weak) protection; httpx-only Tier 2 is
  viable. Fewer moving parts, faster fetches.
- Returns 403, an `<title>Access Denied</title>` page, an
  `errors.edgesuite.net` reference, or a Cloudflare challenge → **anti-bot**.
  Use `scrapers_lib.core.playwright_base.stealth_context`.
- Even stealth fails → add session warming (visit the homepage first, let the
  persistent-profile cookies settle before the target fetch). Dell needs this.
- Warming still fails → the site is off-limits for v0.x free-tier use.
  Flag and move on.

## 4. Catalog of known acquisition patterns

Living table. Add a row when a new Tier 2 source is onboarded.

| Site | Pattern | Endpoint / source | Protection | Granularity | Status |
|---|---|---|---|---|---|
| **Dell** | Shop page carries per-tile `data-url` attributes pointing at `csbapi/unifiedpd/techspecs/{lang}/{country}/{segment}/{customerset}/{sku}`. Call that endpoint through the same stealth Playwright session that loaded the shop page so Akamai cookies ride along. | `www.dell.com/csbapi/unifiedpd/techspecs/...` | Akamai. Needs Playwright + `playwright-stealth` + homepage warming. | Per-SKU (each pre-built BTO tile). | **Verified** (Wave 2a, on Alienware Aurora 16X + Dell XPS 16). |
| **Lenovo (PSREF)** | Product page URL (`/l/Product/<Line>/<Key>` or `/Product/<Line>/<Key>`) carries the `ProductKey` as its last path segment. Both SPA and legacy surfaces hydrate from the same JSON API — call `/api/product/Compare/LoadSpecData?ProductKey=<key>` directly with plain httpx. Response is a 2-layer nested JSON: outer `{code, data: {Classification, GeneralSpecData}}` where `GeneralSpecData[0].GeneralSpecJson` is itself a JSON string carrying `data.SpecData` — a tree of `L1 → L2 → Features → FVs → FVGs → FVGItem` with `{Att, AttV}` pairs at the leaves. Multi-option Features (e.g. 2 CPU SKUs) list alternatives under `FVs`. | `psref.lenovo.com/api/product/Compare/LoadSpecData` | None. | Per-model family (one snapshot per URL; option alternatives embedded as newline-joined rows inside each spec value). | **Verified** (Wave 2b, on Legion Pro 7 16AFR10H + LOQ 15IRX10). |
| **HP (shop PDP)** | **Two-request `curl_cffi` (Wave 2e):** one warmed Chrome-impersonated HTTP/1.1 session fetches both the PDP HTML and a sibling GraphQL hydration endpoint. (1) PDP HTML embeds the full page state as a JSON-encoded HTML comment inside `<div id="data" style="display:none"><!-- {...} --></div>`. Walk that state to `slugInfo.components.pdpCTOConfiguration.configurations` — a list of pre-built "Recommended Configuration" tiles. Each tile carries `configCatentryId` (HP's per-tile SKU, analog of Dell's `data-oc`) and `fullSpecs.technical_specifications` — a list of `{name, tooltip, value:[{value, subheading}]}` with subheadings `"Included in Current Configuration"` / `"Alternate Options"`. ~12 config-picker categories. (2) The PDP body's `<link rel="prefetch" href="/us-en/shop/app/api/web/graphql/page/pdp%2F<slug>/async">` reveals a slug-keyed GraphQL endpoint that returns ~23-26 product-wide Tech Specs categories (Dimensions / Weight / External I/O Ports / Audio / Power supply / Warranty / Sensors etc., set varies by product family) at `data.page.pageComponents.pdpTechSpecs.technical_specifications` — same row shape as the config-picker array. Call it with the same warmed session plus `Referer: <PDP URL>` + `X-Requested-With: XMLHttpRequest` + `Accept: application/json` headers. The async response uses string OR list-of-strings for the inner `value` field; the flattener joins lists with `<br/>` so both shapes share one pipeline. Per-tile (config-picker) values overlay async (product-wide) values on overlap. Async-fetch failure logs at INFO and falls back to config-picker-only data (graceful degradation, mirrors v1.1 behavior). Multi-option values use `<br />` separators within one value field. Emit one snapshot per tile. The async endpoint requires the same `curl_cffi` session that fetched the PDP — a fresh session returns an empty envelope. | `www.hp.com/us-en/shop/pdp/<slug>` for the PDP; sibling `/app/api/web/graphql/page/pdp%2F<slug>/async` for Tech Specs (both on the same warmed session). | None on the PDP HTML for plain httpx specifically (recon proved curl_cffi vs plain httpx return identical bytes — HP's gate is browser-only, not HTTP-layer). The async endpoint requires session cookies established by the warmed PDP fetch. Vanilla AND stealth Playwright are still rejected with `ERR_HTTP2_PROTOCOL_ERROR` on `/shop/pdp/`. | Per-tile (each `configCatentryId`), same as Dell. Async data is product-wide and merged into every tile. | **Verified** (Wave 2b config-picker on Omen Max 16t-ah000 + Pavilion 16z-ag000; Wave 2e async hydration on Omen 16 a58a5av-1 + Pavilion 16z-ag000-redirected-to-OmniBook-5). |
| **ASUS (ROG spec)** | Marketing/spec surface `rog.asus.com[/<region>]/laptops/<line>/<model>/spec/` is plain-httpx-reachable with ~1 MB of SSR'd HTML containing 20+ `<h2>`-headed spec sections (richest Tier 2 coverage so far including Dimensions / Weight / I/O Ports / Power Supply / Security / Expansion Slots / Wireless version — everything HP hides). Canonical asus.com URLs always carry a region/locale segment (`/us/`, `/me-en/`, `/sa-en/`, etc.); the fetcher accepts both region-prefixed and region-less forms (the latter 302-redirects to a regional URL). Each h2 has class `ProductSpec__productSpecItemTitle__<hash>` (CSS module); its next-sibling `<div>` holds per-SKU variant rows with class `ProductSpec__rowItem__<hash>`. **The CSS-module hash suffixes change on every build** — match with `classname.startswith("ProductSpec__productSpecItemTitle__")` rather than exact token. Per-spec values dedupe first-occurrence (ASUS emits one row per SKU permutation; identical rows collapse). One snapshot per URL; multi-SKU alternatives embedded inline. Note that `shop.asus.com` IS the commerce surface for actual prices, but it is **DataDome-gated** and off-limits without paid anti-bot bypass; ROG spec page therefore emits no prices (like Lenovo PSREF). Brand normalized to "ASUS" (JSON-LD says "ROG", a sub-brand); raw.jsonld_brand preserves the original. | `rog.asus.com[/<region>]/laptops/<line>/<model>/spec/` (also works without trailing `/spec/`; region prefix accepted but optional) | None on the ROG spec surface. `shop.asus.com` has DataDome. | Per-model family (one snapshot per URL; alternatives in spec values). | **Verified** (Wave 2b, on ROG Strix G16 2025 + ROG Zephyrus G16 2026). |
| **Acer** | Plain-httpx-reachable SSR HTML on `acer.com/<region-locale>/<brand>/laptops/<model>/pdp/<SKU>`. The `/pdp/<SKU>` suffix is required (bare model URLs return a model-overview page that lists SKUs without specs). The page contains 13 server-rendered `<table class="agw-table agw-table_techSpec">` elements, each scoped to a category by `<caption>` and carrying `<tr><th>label</th><td>value</td></tr>` rows; the `agw-table_techSpec` class shape is stable across regions and product lines despite looking like a CSS-module hash. Use `tier2.base.parse_spec_table()` with selector `table.agw-table_techSpec`. JSON-LD Product enriches name / brand / image_url / price / currency / availability. | `www.acer.com/<region-locale>/<brand>/laptops/<model>/pdp/<SKU>` (e.g. `/us-en/predator/laptops/helios/helios-neo-16s-ai/pdp/NH.U0KAA.001`) | None. Plain `httpx.get()` with Chrome UA returns 200 OK. | Per-SKU (each URL targets exactly one SKU). | **Verified** (Wave 2f, on Aspire 7 Intel + Predator Helios Neo 16s AI + Nitro V 16s AI). |
| **MSI** | Akamai HTTP-layer gate on `us.msi.com` clears with `curl_cffi` + Chrome impersonation + warmed session (visit homepage first, brief sleep, then PDP) — same primitive used by HP and BestBuy in earlier waves. Two surfaces share `SOURCE = "msi"`: (a) `us.msi.com/Laptop/<slug>/Specification` SSR `<table>` with **column-per-SKU** layout (`thead` row of SKU column headers + `tbody` rows pairing `<th>` label with `<td>` per SKU column; 27-31 spec rows universal across gaming + premium AI/Stealth lines — recon initially misread Stealth-AI's main page as having only the JSON-LD `ItemList`, but `/Specification` is in fact universal and the ItemList is supplementary, not a substitute); (b) `us.msi.com/Laptop/<slug>` JSON-LD `ItemList` ~11-field highlights summary on newer AI/Stealth lines only, used as fallback when `/Specification` parse fails. Bare `/Laptop/<slug>` URLs fetch `/Specification` first; explicit `/Specification` URLs skip the fallthrough. One snapshot per `<thead>` SKU column. | `us.msi.com/Laptop/<slug>/Specification` (primary); `us.msi.com/Laptop/<slug>` JSON-LD ItemList (fallback). | Akamai HTTP-layer gate. Trailing-slash toggle ineffective. `curl_cffi` + Chrome impersonation + homepage warming clears it. | Per-SKU on the `/Specification` surface (each `<thead>` column → one snapshot); per-summary on the ItemList fallback (one snapshot for the model-family). | **Verified** (Wave 2f, on Stealth 16 AI+ B3WX + Raider 16 Max HX B2WX + Crosshair 16 HX E14WX). |

### 4.1. Generic pattern types

Every specific site maps to one of these generic shapes. If you find a new
shape, add it here. Most patterns here arose from Tier 2 recon, but
Tier 3 discoveries (notably the `curl_cffi` + HTTP/1.1 bypass for
Akamai-on-HTTP/2 sites) belong here too — any fetcher may need them.

| Shape | Description | Fetch approach |
|---|---|---|
| Internal API + anti-bot | Shop page hints at an endpoint; endpoint is bot-protected. | Stealth Playwright session to bootstrap cookies, then `page.context.request.get()` for the API call. (Dell.) |
| Dedicated spec-sheet site | Separate domain or subdomain hosts the datasheet. | Plain `httpx`; separate fetcher file per domain if needed. (Lenovo PSREF candidate.) |
| SSR'd in product page | Specs are in the raw HTML as tables or JSON-LD. | `base.parse_spec_table` or `base.parse_product_jsonld`. |
| Framework state blob | Product model serialized into a `<script>` tag. | `base.parse_inline_json(script_id=...)` or similar. |
| Lazy-loaded on scroll/click | DOM fills in after user interaction. | Playwright with scroll-to-bottom or click-then-wait, then re-read DOM. |
| PDF datasheet | Last resort. Manufacturer exposes a data-sheet PDF only. | Add a PDF-parsing dependency (pdfplumber / pypdf). **Flag the user** before adding a new dep. |
| **Akamai HTTP/2-layer bot gate** (Wave 2c) | Site serves real HTML to browsers but drops bot clients at the HTTP/2 protocol layer — signatures include `RemoteProtocolError: Server disconnected` (plain httpx), `net::ERR_HTTP2_PROTOCOL_ERROR` (stealth Playwright), or `HTTP/2 stream N not closed cleanly: INTERNAL_ERROR` (curl_cffi on HTTP/2). TLS handshake completes; the gate is specifically HTTP/2 frame / fingerprint analysis. | `curl_cffi` with Chrome TLS impersonation **forced onto HTTP/1.1** (`CurlHttpVersion.V1_1`), plus a homepage warm-up to seat Akamai cookies. HTTP/1.1 avoids the gate entirely; Chrome impersonation still clears the TLS check. (BestBuy `/site/...` PDPs — `tier3/bestbuy`. New dep `curl_cffi>=0.7` added Wave 2c.) |
| **Two-request session — PDP + sibling hydration endpoint** (Wave 2e) | Site SSRs partial spec data into the PDP, then hydrates the rest from a slug-keyed JSON endpoint discoverable via a `<link rel="prefetch">` near the top of the PDP body. Hydration endpoint requires the same session (cookies) that fetched the PDP — a fresh session returns an empty envelope. The HTTP layer itself may not be the gate; HP's PDP HTML is plain-httpx-reachable (recon proved curl_cffi delta is ~0.7% bytes), but the hydration endpoint is session-scoped. | One warmed `curl_cffi` + Chrome + HTTP/1.1 session (kept open as a context manager) makes both calls. Derive the hydration URL from the PDP URL (HP: `/pdp/<slug>` → `/app/api/web/graphql/page/pdp%2F<slug>/async`). Send `Referer: <PDP URL>` + `X-Requested-With: XMLHttpRequest` + `Accept: application/json` on the hydration call. Best-effort: log + fall back to PDP-only data on hydration failure. (HP `/shop/pdp/` Tech Specs — `tier2/hp`.) |

## 5. Decision tree for a new manufacturer

Walk this in order. Stop at the first step whose answer is yes.

1. **Is there a dedicated spec-sheet site?** (Web search: `"<manufacturer>"
   product specifications site` / `"<manufacturer>" datasheet`.) If yes and
   it looks authoritative → use it; write an httpx-based fetcher on that
   separate domain. (Lenovo PSREF is the prototype.)
2. **`httpx.get(product_url)` with a current Chrome UA — does it return real
   HTML?** If no (403 / Access Denied / obviously wrong content) → you will
   need Playwright + stealth. Continue.
3. **Open DevTools Network tab on a real product page and click the spec
   feature. Does an XHR fire with a promising endpoint?** If yes → use the
   Dell pattern. Extract the endpoint from a page attribute
   (`data-url` / `data-endpoint` / similar) so future URL variations don't
   require code changes. Call the endpoint through the browser context.
4. **Are specs already in the raw HTML source?** → Use `base` parsers
   (`parse_spec_table` / `parse_product_jsonld` / `parse_inline_json`).
5. **Does scrolling hydrate them?** → Playwright with scroll step before
   `page.content()`.
6. **Does clicking reveal them?** → Playwright with click-then-wait.
7. **Is there a PDF datasheet URL?** → Last resort; discuss adding pdfplumber
   with the user before writing code.

Verify on at least **two unrelated product URLs from the same site** before
locking in a pattern. Generality check is not optional.

## 6. Output format discipline

Regardless of acquisition pattern, every Tier 2 fetcher emits the same
`ProductSnapshot` shape so downstream code is source-agnostic.

- **`source`** — short site slug: `"dell"`, `"lenovo"`, etc.
- **`source_id`** — the site's canonical stable identifier for this variant
  (Dell Order Code, Lenovo MTM, HP product number, etc.). Must round-trip to
  the same URL/specs on re-fetch.
- **`variant_key`** — tile / configuration identifier when a single URL yields
  multiple variants. `None` when only one.
- **`anchor_id`** — from URL-map attribution via `attribute_url(url, source,
  anchors)`. **Raise `ValueError` if no anchor matches the URL.** No silent
  synthesis of anchors — consumers must declare what they are tracking.
- **`specs`** — verbatim values from the site. The library does **no**
  cross-manufacturer normalization (`"Memory"` vs `"RAM"` vs `"System Memory"`
  is a consumer concern).
- **`raw`** — include `{"spec_source": "..."}` so future debugging can tell
  where specs came from (API response, SSR table, fallback bullets, etc.).
- **Partial success is first-class.** If the primary data source fails for one
  variant (API 500, malformed JSON, whatever), fall back to whatever lesser
  source is available, log a warning, and still emit the snapshot with what
  you have.

## 7. Worked example: the Dell case study

How Dell was added in Wave 2a. Use this as the template for future recon
narratives.

**Step 1. Naive fetch.** `fetch_rendered_html(url)` with Wave 1 stealth
defaults → 397-byte Akamai "Access Denied" page. Signal: Wave 1 stealth was
insufficient. (The Wave 1 UA said Chrome-124; installed Chromium was 145. The
mismatch was a cheap bot signal.)

**Step 2. Stealth upgrade.** Added `playwright-stealth` fingerprint masking,
current Chrome-145 UA, plus session warming (visit `dell.com/en-us/` first so
Akamai cookies settle into the persistent profile). → 3.3 MB of real HTML. ✓

**Step 3. Map the page.** Searched for tile-like structures. Found three
elements carrying a `data-oc` attribute, each with a distinct value — Dell's
per-tile Order Code (their SKU). Same count and shape held on a second product
(checked later in step 6).

**Step 4. Where are the detailed specs?** Counted `<table>` elements in the
HTML. **Zero.** Only six summary bullets per tile — marketing copy, not a full
spec sheet. At this point the naïve plan (scrape the in-page spec section) was
dead.

**Step 5. DOM attribute search.** Ran the §3.2 technique: searched all element
attributes for any string containing `"tech-spec"`. Found three values:

```
data-url="/csbapi/unifiedpd/techspecs/en/us/bsd/04/useac16251hbtshqfq"
data-url="/csbapi/unifiedpd/techspecs/en/us/bsd/04/useac16251hbtshqmy"
data-url="/csbapi/unifiedpd/techspecs/en/us/bsd/04/useac16251wmlkcto03"
```

One per tile. Endpoint Dell's own frontend hits when the user clicks "Tech
Specs." This is the answer.

**Step 6. Verify the endpoint.**
- `httpx.get(endpoint, headers=...)` → 403 Akamai. Plain HTTP not enough.
- `page.context.request.get(endpoint, ...)` through the existing stealth
  session → 200 OK, 4 KB HTML fragment, twenty labeled spec categories:
  processor (full detail incl. cache and clocks), GPU, memory, storage,
  display, ports (multi-line), slots, dimensions & weight, keyboard, camera,
  audio, chassis, wireless. ✓

**Step 7. Generality check.** Repeated the probe on Dell XPS 16 (different
product line, different marketing layout). Same structure: three tiles, same
`csbapi/unifiedpd/techspecs` endpoint pattern, same HTML-fragment response
shape. ✓ Pattern is Dell-wide, not Alienware-specific.

**Step 8. Lock it in.**
- Fetcher does one stealth Playwright session per product URL: warm → fetch
  product page → harvest `data-url` attributes → call each endpoint via
  `page.context.request.get()` → parse the HTML fragments → emit one
  `ProductSnapshot` per tile with ~20 rich spec categories.
- Fall back to in-page tile bullets (6 short specs) when a techspecs endpoint
  fails for a single tile — partial success.

### Generalizable lessons

1. **What the UI fires is the authoritative data path.** Find the endpoint
   the manufacturer's own frontend calls; prefer that over scraping rendered
   DOM. The site can redesign the shop page and the endpoint usually survives
   because their own UI still needs it.
2. **The same browser session that loaded the page is the most durable way
   to call a protected API.** Anti-bot systems (Akamai, Cloudflare, Kasada)
   care about session cookies built over time, not UA alone. `page.context.
   request.get()` is the primitive that gets this right.
3. **Verify on two unrelated products before committing to a pattern.** One
   page is anecdote; two from different lines is evidence.
4. **Read every DOM attribute, not just class and id.** Framework authors put
   configuration into `data-*` attributes; they're a goldmine for discovering
   internal endpoints.

### Code artifacts

The scripts that did the reconnaissance live in
[`scripts/dell/`](../scripts/dell/). They are re-runnable when Dell
redesigns and the committed fixtures need refreshing. Model future-site
reconnaissance on them — don't start from scratch.

## 8. Acceptance criteria

A new Tier 2 source is "done" when:

- [ ] Registered via `@register("<source_name>")`.
- [ ] Signature matches the library contract:
      `fetch_<site>(url, anchors=None, **opts) -> list[ProductSnapshot]`.
- [ ] URL-map attribution applied; raises `ValueError` if no anchor matches.
- [ ] Pure-parse function separated from I/O (`parse_<site>_product_page(html,
      url, ...) -> list[ProductSnapshot]`) so unit tests can hit it without
      network.
- [ ] Unit tests against committed HTML fixtures for **≥ 2 unrelated product
      URLs** from the same site. Generality check is a test, not a vibe.
- [ ] Gated integration test (`SCRAPERSLIB_LIVE_TESTS=1`) against a live URL.
- [ ] New row in [`docs/ARCHITECTURE.md §11`](ARCHITECTURE.md) with honest
      coverage notes and known limitations.
- [ ] New entry in [§4 of this doc](#4-catalog-of-known-acquisition-patterns)
      describing the acquisition pattern used.
- [ ] Reconnaissance scripts committed to `scripts/<site>/` with a short
      `README.md` pointing back at this doc.
- [ ] CHANGELOG `[Unreleased]` bullet under **Added**.
