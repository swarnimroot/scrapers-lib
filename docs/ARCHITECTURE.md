# scrapers-lib — Architecture

**Status:** draft &nbsp;·&nbsp; **Last updated:** 2026-04-21 &nbsp;·&nbsp; **Library version:** 0.1.0 (pre-release)

> Draft-stage document. Sections marked *(subject to revision)* may change as Wave 1 core code lands and reveals gaps. All details will be reviewed and re-confirmed at v1.0.0.

---

## 1. Overview

scrapers-lib is organized as a small set of core primitives plus a growing library of per-source fetchers grouped by reliability tier. Consumers compose these primitives to drive their own pipelines; the library itself stays agnostic to what is being tracked.

```
scrapers-lib/
  scrapers_lib/
    core/
      schemas.py            # Anchor, ProductSnapshot, RawMention
      attribution.py        # regex & URL-map attribution gates
      cache.py              # diskcache wrapper
      rate_limiter.py       # per-domain token buckets
      http_client.py        # httpx + retry/backoff/UA rotation
      playwright_base.py    # stealth Playwright helpers
      robots.py             # robots.txt awareness
      logging_config.py     # stdlib logging setup
      scheduler.py          # persistent job queue + worker
      registry.py           # internal fetcher registry
    tier1/                  # API / feed-based, reliable
      reddit.py, rss.py, article.py, youtube.py, bestbuy_api.py
    tier2/                  # direct URL, moderate reliability
      dell.py, hp.py, lenovo.py, asus.py, acer.py, msi.py
    tier3/                  # scraping, fragile
      bestbuy.py, amazon.py
  tests/
  docs/
  pyproject.toml
  README.md
  .env.example
  .gitignore
  LICENSE
```

> The tier folders are not closed sets. New sources fit the same pattern — see §12.2 for how to add one.

## 2. Tier model

Sources are categorized by **reliability**, not by subject matter.

| Tier | Access method | Reliability | Examples |
|---|---|---|---|
| **1** | Official APIs and feeds | High — documented quotas, stable interfaces | Reddit (PRAW), RSS feeds, YouTube transcripts, BestBuy Developer API |
| **2** | Direct URLs, JS-heavy pages | Moderate — parsers may need updates after site redesigns | Manufacturer product pages |
| **3** | Scraping pages behind bot detection | Low — expect partial failures, redesigns, rate limits | Retailer product and review pages |

Consumers pick tiers based on what their project needs. Tier 1 is preferred unless a consumer explicitly needs data that only exists in higher-risk tiers.

## 3. The three schemas

Every fetcher returns one or both of these types. All are Pydantic v2 models; consumer code can use them directly or convert to plain dicts.

### 3.1 Anchor

An **Anchor** is a thing the consumer is tracking. It is consumer-defined; the library never creates one. Anchors drive attribution: for a piece of text or a product page to be relevant to a project, the library must be able to link it to one of that project's Anchors.

Fields:

- `anchor_id` — consumer-chosen stable slug. Required.
- `anchor_type` — one of `product`, `game`, `company`, `topic`, `custom`. Required. The type is advisory for consumer logic; the library does not branch on it.
- `name` — human-readable name. Required.
- `aliases` — list of alternate names. Optional.
- `attribution_regex` — struct with `primary` (required, non-empty list), `corroboration` (optional list), `exclusion` (optional list). Tokens are literal by default and auto-escaped for regex; prefix with `re:` for raw regex. Described in §4.
- `source_urls` — dict `{source_name: url}` for sources that use URL-pre-attribution. Optional.
- `attributes` — free-form dict `{str: Any}` for type-specific data the consumer cares about (brand, model, cpu, gpu, publisher, release_year, entity_type, etc.). Optional. The library treats this as opaque metadata; it is echoed into outputs but never interpreted.
- `notes` — free-form string. Optional.

### 3.2 ProductSnapshot

A **ProductSnapshot** is a point-in-time observation of a product listing on a specific source. Multiple snapshots accumulate over time; consumers diff them to derive history.

Fields:

- `source` — source name string (e.g., `"dell"`, `"bestbuy_api"`). Required.
- `source_id` — source-specific stable identifier (SKU, ASIN, part number). Required.
- `variant_key` — optional, for pages with configurable variants (BTO configurators, multi-config retail listings).
- `anchor_id` — the Anchor this snapshot is attributed to. Required.
- `url` — canonical product URL. Required.
- `title` — as shown on the source. Required.
- `brand`, `model`, `category` — optional normalized fields.
- `config_summary` — human-readable variant description (e.g., `"RTX 5060 / 32GB / 1TB"`). Optional.
- `price`, `list_price` — `Decimal`. Optional (some sources don't expose pricing).
- `currency` — string, default `"USD"`.
- `in_stock` — bool. Optional; `None` means unknown.
- `availability_text` — raw availability string. Optional.
- `rating` — float 0–5. Optional.
- `review_count` — int. Optional.
- `image_url` — string. Optional.
- `specs` — free-form dict `{str: str}`. Sources fill what they expose; no cross-site normalization.
- `raw` — optional dict containing the raw source payload for debugging.
- `fetched_at` — datetime (UTC). Always populated by the library.

### 3.3 RawMention

A **RawMention** is a piece of verbatim text from a community, news, or transcript source, attributed to an Anchor.

Fields:

- `mention_id` — deterministic ID (see §4.3). Required.
- `source` — source name string (e.g., `"reddit"`, `"rss"`, `"youtube"`). Required.
- `source_type` — one of `post`, `comment`, `article`, `video`, `transcript_chunk`. Required.
- `source_url` — URL the mention came from. Required.
- `source_title` — title / headline / post subject. Optional.
- `author`, `author_id` — optional.
- `channel` — subreddit name, YouTube channel, publication name. Optional.
- `parent_id` — e.g., Reddit post ID for a comment. Optional.
- `published_at` — datetime (UTC). Optional where source doesn't expose it.
- `fetched_at` — datetime (UTC). Always populated.
- `raw_text` — verbatim text. Required, non-empty.
- `attribution` — struct with `anchor_id`, `confidence` (0–1), `method` (`regex` | `url_map` | `manual`), `matched_tokens` (optional list).
- `raw` — optional dict.

## 4. Attribution

Attribution is the gate that decides whether a piece of fetched text belongs to one of the consumer's Anchors. This is a library concern because every source does it slightly differently but the *patterns* are universal.

### 4.1 Regex gate

For community and news text where membership is not implied by the URL. Applied per unit (per Reddit comment, per article paragraph, per transcript chunk).

Rules:

- `primary` tokens (required): at least one must match.
- `corroboration` tokens (optional): if specified, at least one must also match. Reduces false positives for ambiguous names.
- `exclusion` tokens (optional): if any match, the unit is dropped.

**Drop-over-guess discipline:** if a unit matches primary but ambiguously (e.g., matches two Anchors' primary tokens and no corroboration disambiguates), it is routed to an `unassigned` log, not forced into one Anchor. Consumers can inspect unassigned rates as a regex-quality signal.

### 4.2 URL-map gate

For sources where the URL itself uniquely identifies the Anchor (a manufacturer product page, a review article dedicated to a specific product). Consumer provides `Anchor.source_urls`; the fetcher pre-attributes every unit on the page to that Anchor with `confidence = 1.0`.

### 4.3 Deterministic mention IDs

Every RawMention gets a deterministic ID so re-fetches collide rather than duplicate. Patterns:

- Reddit post: `reddit_post_{post_id}`
- Reddit comment: `reddit_comment_{comment_id}`
- RSS article: `rss_{source_slug}_{article_guid}`
- Manufacturer page paragraph: `{source}_{anchor_id}_{paragraph_index}`
- YouTube transcript chunk: `youtube_{video_id}_chunk_{index}`

## 5. Usage patterns

The library supports two ways to consume it. Both share the same underlying fetchers.

### 5.1 Direct fetcher calls — one-off, synchronous

```python
from scrapers_lib.core.schemas import Anchor
from scrapers_lib.tier1 import rss

anchor = Anchor(
    anchor_id="example_topic",
    anchor_type="topic",
    name="Example Topic",
    attribution_regex={"primary": ["example", "Example Topic"]},
)

mentions = rss.fetch_feed(
    "https://example.com/feed.xml",
    anchors=[anchor],
)
```

Use when: small projects, urgent queries, scripts.

### 5.2 Scheduler — queue-based, long-running

```python
from scrapers_lib import Scheduler

sched = Scheduler(
    state_file="./data/jobs.sqlite",
    result_sink=my_save_callback,
    domain_budgets={"example.com": "200/day"},
)

for url in my_urls:
    sched.enqueue(url, source="rss", anchors=my_anchors)

sched.run_worker(mode="forever")
```

Use when: many URLs, patient pacing, 24x7 workers, rate-limit-sensitive sources (especially Tier 3).

The Scheduler owns no state larger than its SQLite file and its per-domain persistent Playwright browser profiles. The library is otherwise stateless.

## 6. Scheduler

Persistent job queue backed by SQLite (stdlib). Survives laptop restart.

Key properties:

- **Per-domain budgets.** E.g., `"amazon.com": "100/day"`. When budget is exhausted, that domain sleeps until the window resets.
- **Adaptive backoff.** On 429 / 403 from a domain, that domain backs off for hours while other domains keep working.
- **Persistent browser profiles.** One Chromium profile per domain for Tier 2/3; cookies and history accumulate (helps defeat behavioral bot detection).
- **Two run modes.** `forever` polls continuously; `until_empty` drains then returns.
- **Callback result delivery.** Consumer provides `result_sink(batch)`; library is storage-agnostic.
- **Stats.** `sched.stats()` returns per-domain success/failure counts and last-attempt timestamps.
- **Concurrency model.** One worker process per consumer. Within a worker, jobs execute sequentially but dispatch is budget-aware: a domain that is rate-limited does not block jobs for other domains. Consumers who want true parallelism across domains can run multiple worker processes.

## 7. Caching

Per-URL cache with configurable TTL per source. Cache keys default to the full URL; fetchers can override when additional inputs belong in the key (e.g., pagination offset, session).

TTL defaults (overridable per fetch):

| Source category | Default TTL |
|---|---|
| Reddit | 1 hour |
| RSS feeds | 1 hour |
| Article bodies | 30 days |
| Manufacturer spec pages | 7 days |
| Retailer product pages | 1 day |
| Retailer reviews | 7 days |
| YouTube transcripts | 30 days |

Cache is per-consumer (consumer provides the directory). Cache state never leaves the consumer's workspace.

## 8. Rate limiting and retry

Per-domain token bucket. Defaults are conservative: roughly 30–60 seconds between requests for Tier 3 sources, faster for Tier 1/2.

HTTP retries (httpx-based fetchers): exponential backoff on 429 / 503, bounded retry count, `Retry-After` header respected when present.

Playwright retries (Tier 2/3): up to 3 attempts with increasing delay; on hard block (403 / CAPTCHA page), job is marked failed and backoff is extended at the domain level.

## 9. Robots.txt

Respected by default. Per-call `ignore_robots=True` override exists for sites whose robots.txt is known to be aggressive beyond what their ToS requires. Consumers who override should document why.

## 10. Error and logging posture

- **Errors bubble up as exceptions.** No silent failures. When fetching fails, the exception carries context (URL, source, status code, parsing step); the Scheduler catches centrally and records.
- **Structured logging.** stdlib `logging`, stderr by default, per-module loggers (e.g., `scrapers_lib.tier2.dell`). Consumers configure levels.
- **No secrets in logs.** API keys and credentials are loaded via `python-dotenv`; logs reference them by name, never value.
- **Partial success is a first-class outcome.** A fetcher that gets 80% of a page's specs returns what it has; missing fields are `None`, not faked.

## 11. Per-source coverage *(subject to revision)*

This table will be filled in and refined as each fetcher is built. v0.1 shows intended coverage.

| Source | Tier | Schema | Fields reliably populated | Known limitations |
|---|---|---|---|---|
| Reddit (PRAW) | 1 | RawMention | title, body, author, score, timestamps | 60 req/min API cap; needs OAuth app |
| RSS (feedparser) | 1 | RawMention | title, summary, author, published_at | full body needs follow-up via `tier1.article` |
| Article body (trafilatura) | 1 | RawMention | raw_text (full article) | partial failures on paywalled sites |
| YouTube transcripts | 1 | RawMention | transcript chunks, video metadata | ~15% of videos lack captions; no fallback in library |
| BestBuy Developer API | 1 | ProductSnapshot | One snapshot per SKU via the Developer API at `api.bestbuy.com/v1/products/<SKU>.json`; URL-map attribution by the bestbuy.com PDP URL (SKU extracted from `.../<SKU>.p` path or `?skuId=<SKU>` query). Populates `price` (sale price when `onSale=true`, else `regularPrice`), `list_price` (`regularPrice` when on sale), `in_stock` (from `orderable`/`onlineAvailability`/`inStoreAvailability`), `availability_text` (human-readable), `rating` + `review_count` (`customerReviewAverage`/`customerReviewCount`), `brand` (`manufacturer`), `model` (`modelNumber`), `category` (leaf of `categoryPath`), `image_url` (`largeFrontImage` with fallbacks), `specs` (flat `details[]` name/value pairs — ~20-30 rows), `config_summary` (first three `features[]` strings). Credential via `BESTBUY_API_KEY` env var; missing key raises `RuntimeError`; 403 raises on bad key; 404 raises on unknown SKU | No user reviews (API does not expose them — use `tier3/bestbuy` for reviews); partial success on optional fields (missing rating / image / specs do not fail the parse) |
| Dell | 2 | ProductSnapshot | One snapshot per pre-built tile; specs from Dell's `csbapi/unifiedpd/techspecs` endpoint (~20 categories: processor, GPU, memory, storage, display, ports, slots, dimensions & weight, keyboard, camera, audio, chassis, wireless, services); `price` / `list_price`; brand, rating, `image_url` from JSON-LD | Akamai-protected — requires stealth browser session with session warming; pure configurator-only pages (no pre-built tiles) not yet supported; per-SKU modal-specs only (line-level datasheet not harvested) |
| Lenovo (PSREF) | 2 | ProductSnapshot | One snapshot per model-family URL; specs from `psref.lenovo.com/api/product/Compare/LoadSpecData` JSON endpoint (50+ feature keys across 8 top-level categories: Performance, Design, Connectivity, Security & Privacy, Service, Accessories, Operating Requirements, Certifications); multi-option Features (multiple CPUs / GPUs / memory tiers) serialized as newline-joined alternatives per feature; `brand` fixed to "Lenovo"; `category` from PSREF's own `Classification` field | No prices, no stock, no rating data (PSREF is a spec reference, not a shop); per-model-family granularity, not per-SKU (option alternatives embedded in each Feature value); `image_url` not yet extracted (available via a separate overview call, not the spec endpoint); Manageability / Environmental categories in schema but empty on most consumer laptops |
| HP (shop PDP) | 2 | ProductSnapshot | One snapshot per pre-built "HP Recommended Configuration" tile (typically 3) with per-tile `source_id`/`variant_key` = HP's `configCatentryId`; specs from the hidden `<div id="data"><!-- {state JSON} --></div>` blob at `slugInfo.components.pdpCTOConfiguration.configurations[*].fullSpecs.technical_specifications` (11–12 config-picker categories: Operating system, Processor and graphics, Memory, Storage, Display, Color, Personalization, Keyboard, Wireless technology, Primary battery, Office software, McAfee Security — consumer lines sometimes merge Processor/Graphics/Memory into one); multi-option values serialize as newline-joined alternatives with current configuration on line 0; per-tile `price` / `list_price`, `image_url` from the tile; `rating` / `review_count` from JSON-LD | Plain httpx delivers the state blob but the "Tech Specs" section (Dimensions, Weight, Ports, Power supply, Audio beyond brand, Sensors, Security hardware, Warranty, certifications like EPEAT/Energy Star) is hydrated client-side and IS NOT in the httpx response — those ~20 additional categories would require bypassing HP's aggressive browser bot gate (vanilla Playwright and library stealth both get `ERR_HTTP2_PROTOCOL_ERROR` even with homepage warming) OR fetching HP's QuickSpecs PDFs from `h20195.www2.hp.com/v2/GetDocument.aspx?docname=<ID>` (feasible but needs a PDP-SKU → QuickSpecs-doc-ID lookup layer, not yet built); JSON-LD Product name on HP PDPs has been observed carrying stale template names (e.g. Pavilion PDP naming a different OmniBook) so title is pulled from the tile, not from JSON-LD |
| ASUS (ROG spec) | 2 | ProductSnapshot | One snapshot per model-family URL; specs from `rog.asus.com/laptops/<line>/<model>/spec/` SSR'd `<h2>`-headed sections (20+ categories covering Operating System, Processor, Graphics, Neural Processor, Display, Memory, Storage, Expansion Slots, I/O Ports, Keyboard and Touchpad, Camera, Audio, Network and Communication, Battery, Power Supply, AURA SYNC, Device Lighting, Weight, Dimensions, Security, Microsoft Office, Xbox Game Pass, Included in the Box — richest Tier 2 coverage so far including the Dimensions/Ports/Weight axes HP cannot deliver); multi-SKU option alternatives for every spec embedded as newline-joined, first-occurrence-deduped variant rows (ASUS emits one row per SKU permutation; identical rows collapse to a single line); `brand` normalized to "ASUS" for cross-vendor grouping (JSON-LD declares sub-brand "ROG" which is preserved under `raw.jsonld_brand`); `title` / `image_url` from JSON-LD Product | No prices on the spec surface (ROG marketing site, not shop); `shop.asus.com` IS the e-commerce surface but is DataDome-protected and off-limits without paid bypass; category SET varies per product line (e.g. Zephyrus omits AURA SYNC which Strix has) — parser walks whatever h2s are present without hard-coding category names; ASUS's CSS-module class hashes (e.g. `ProductSpec__productSpecItemTitle__JVvSd`) change on every build, so selector uses a substring prefix match rather than the full token |
| Acer, MSI | 2 | ProductSnapshot | **Deferred (post-demo)** — not required for Demo 2 max-spec comparison since Dell/HP/Lenovo/ASUS cover the four major gaming-laptop manufacturers. Will be revisited after the demo ships if broader coverage becomes necessary. | n/a |
| BestBuy (reviews) | 3 | RawMention | One `RawMention` per inline PDP review (typically 5 per fetch) extracted from the initial JSON-LD `Product.review` list. Populates `raw_text` (reviewBody), `source_title` (review name), `author` (`author.name`), `parent_id` (SKU), `raw.star_rating` (`reviewRating.ratingValue`), `source_url` (deep link to `bestbuy.com/site/reviews/name/<SKU>`), deterministic `mention_id` via hash of author+body (BestBuy JSON-LD carries no stable per-review IDs). Fetched via `curl_cffi` with Chrome TLS impersonation forced onto **HTTP/1.1** — the only combination that bypasses Akamai's HTTP/2 RST-stream bot gate on `bestbuy.com/site/...` URLs (plain httpx drops at transport, stealth Playwright fails with `ERR_HTTP2_PROTOCOL_ERROR`, curl_cffi on HTTP/2 fails with `HTTP/2 INTERNAL_ERROR` across every Chrome version). Session warms against homepage first. | `published_at` is `None` — JSON-LD on BestBuy PDPs does not carry `datePublished`; `/site/reviews/name/<SKU>` surface does and is the upgrade path. Review coverage capped at ~5 per fetch (PDP inline cap); full pagination at `/site/reviews/name/<SKU>?page=N` is a future-wave enhancement. New dependency `curl_cffi>=0.7` (free, open-source, drop-in requests-like API). |
| Amazon (product + reviews) | 3 | ProductSnapshot + RawMention | Two separately-registered fetchers in one module: `amazon` → one `ProductSnapshot` per ASIN; `amazon_reviews` → one `RawMention` per inline PDP review (typically 8-12 per fetch). Plain httpx with a current Chrome UA works directly against `amazon.com/dp/<ASIN>` — no stealth, no session warming. Product snapshot populates `price` (`.priceToPay .a-offscreen`), `rating` (`#acrPopover` title), `review_count` (`#acrCustomerReviewText` aria-label), `title` (`#productTitle`), `brand` (`#bylineInfo` → `#visitStoreDesktopUrl` → `#brandLogoHiResByline` fallback chain for standard-vs-premium PDP render variants), `image_url` (`#landingImage` with `data-old-hires` preferred), `availability_text` + `in_stock` (`#availability` + heuristics), `config_summary` (first three `#feature-bullets` strings), `specs` (all `<table class="prodDetTable">` tables merged — 50+ rows across Memory / Battery / Ports & Slots / Additional details expanders). Each review `RawMention` carries body / title / author + author-ID (from `/gp/profile/amzn1.account.<ID>` link) / `published_at` (parsed from "Reviewed in ... on Month DD, YYYY") / `raw.star_rating` / `raw.verified_purchase` / `raw.helpful_count`; deterministic `mention_id` from Amazon's own R-prefix review ID. | The dedicated `/product-reviews/<ASIN>/` page redirects unauthenticated clients to a sign-in wall; PDP-inlined reviews (~10) are therefore the reachable subset without Amazon credentials. Amazon stays in Tier 3 because redesigns are frequent, sustained traffic from one IP gets rate-limited, and review coverage is partial by design. Amazon JSON-LD is absent on Electronics PDPs (selector-based extraction only). |

## 12. Plugin registry and source extension

### 12.1 Internal fetcher registry

The internal fetcher registry (`core/registry.py`) maps source-name strings to fetcher callables. All fetchers follow the same signature:

```
Callable[[str, list[Anchor] | None, **fetch_options], list[RawMention] | list[ProductSnapshot]]
```

A future plugin-registration API (`register_fetcher(name, fn)`) can be added without breaking existing code. Not built in v0.1; the signature discipline is the preparation.

### 12.2 Adding a new source

> **Tier 2 sources (manufacturer spec pages) — read [`docs/ADDING_A_SOURCE.md`](ADDING_A_SOURCE.md) first.** That guide covers reconnaissance techniques, per-manufacturer acquisition patterns (Dell's internal API, Lenovo's likely PSREF, etc.), the decision tree for picking a pattern, and the Dell case study. The generic steps below still apply; Tier 2 has additional discipline on top.

The tier folders (`tier1/`, `tier2/`, `tier3/`) are not closed sets. New sources are added by dropping a new file into the appropriate tier. The steps:

1. **Pick the tier** based on reliability:
   - **Tier 1** — the source has an official API, a public feed (RSS), or a stable documented endpoint. High reliability expected.
   - **Tier 2** — the source requires scraping a public page that is JS-heavy or moderately structured (e.g., a manufacturer product page). Moderate reliability.
   - **Tier 3** — the source requires scraping behind bot detection or with significant risk of blocks (e.g., retailer review pages).

2. **Create the fetcher file** at `scrapers_lib/tier{N}/{source_name}.py`. Implement one or more functions matching the standard signature:

   ```python
   def fetch_xxx(
       url: str,
       anchors: list[Anchor] | None = None,
       **fetch_options,
   ) -> list[RawMention] | list[ProductSnapshot]:
       ...
   ```

3. **Register the source name** at the bottom of the new file:

   ```python
   from scrapers_lib.core.registry import register_fetcher
   register_fetcher("new_source", fetch_xxx)
   ```

4. **Add credentials** to `.env.example` if the source requires them; load them inside the fetcher via `os.environ`.

5. **Add an integration test** at `tests/tier{N}/test_{source_name}.py`, gated by `SCRAPERSLIB_LIVE_TESTS=1`, covering at minimum a happy-path fetch and schema validation.

6. **Update the per-source coverage table** in §11 with what the fetcher reliably populates and its known limitations.

The library's core (schemas, Scheduler, cache, rate limiter, attribution) does not change when a new source is added. This extensibility is what keeps the library universal: adding Walmart, Newegg, Target, or any other source is a matter of writing one fetcher file; the rest of the infrastructure adapts automatically.

## 13. Testing and maintenance

- **Unit tests** per core module; no network. Cover schema validation, attribution logic, mention-ID generation, rate limiter behavior, cache key logic, Scheduler state transitions.
- **Integration tests** per fetcher, gated by `SCRAPERSLIB_LIVE_TESTS=1`. Off by default so tests don't hit sites incidentally.
- **Site-drift canary.** Running the integration suite periodically (weekly recommended) surfaces parser breakage from site redesigns. A failed integration test is the signal that a fetcher needs maintenance.
- **When a site breaks:** fetcher is marked `degraded` in logs; consumers learn via returned warnings or `sched.stats()`. Fix cadence is on-demand, not scheduled.

## 14. Versioning and deprecation

- Semantic versioning. Pre-1.0: `0.x.y`, public APIs may change between minor versions.
- At 1.0.0: public schemas and fetcher signatures frozen. Deprecations go through one minor-version warning before removal.
- Git tags mark releases (`v0.1.0`, `v0.2.0`, …) on the local repo.
- Consumers install via `pip install -e ../scrapers-lib` and note the tag they are testing against.

## 15. Security and secrets

- `.env` is in `.gitignore` by default.
- `.env.example` documents every credential the library supports; updated as new sources arrive.
- Credentials are loaded via `python-dotenv` at runtime; the library reads only specific named env vars.
- Logs redact credential values.

## 16. What this architecture does not decide (deferred)

- Spec-vocabulary normalization across manufacturers.
- Cross-Anchor relationship modeling.
- Distributed scheduling (multiple workers coordinated via shared state).
- Plugin registration API (signature is ready; API is not built).
- CI / published packages (no PyPI release in v0.x; local `pip install -e` only).

These may be added in future versions based on consumer demand. None block v1.0.
