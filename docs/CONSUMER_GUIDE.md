# Consumer Guide — building projects on scrapers-lib

**Status:** stable &nbsp;·&nbsp; **Last updated:** 2026-05-12 &nbsp;·&nbsp; **Targets:** scrapers-lib v1.4.0+

This guide is for people building a *consumer project* that uses
`scrapers-lib` as a data-fetching library. The library returns typed
data; the consumer decides what to do with it. No part of this guide
requires modifying `scrapers-lib` itself — everything here is written
from the consumer side.

If you're looking for how the library itself is structured, read
[`ARCHITECTURE.md`](ARCHITECTURE.md). If you're adding a new source
*to* the library, read [`ADDING_A_SOURCE.md`](ADDING_A_SOURCE.md).
This guide is the middle lane: how to consume what's already there.

---

## 1. Mental model

`scrapers-lib` is **infrastructure, not an application.** It knows
how to fetch, rate-limit, retry, attribute, and normalize data from
15 registered sources into three stable schemas (`RawMention`,
`ProductSnapshot`, `Anchor`). It knows nothing about what *you*
track, where you persist, or what you do with the data downstream.

Your consumer project owns:

- **Anchors** — the products, topics, games, or companies you care about.
- **Enqueue logic** — which URLs to fetch, from which sources, how often.
- **Persistence** — where you store fetched data (SQLite? DuckDB? JSON?).
- **Analysis** — sentiment, aggregation, alerting, dashboards.

`scrapers-lib` gives you:

- A `Scheduler` that runs 24x7 and walks through URLs patiently, respecting per-domain rate limits and robots.txt.
- Registered fetchers for 15 sources — you pass a URL + source name + anchors; you get back typed `RawMention` or `ProductSnapshot` rows.
- Attribution helpers that tie fetched content to your anchors.
- A deterministic mention-ID scheme so re-fetches collide rather than duplicate.

---

## 2. Setting up a consumer project

### Directory layout

Consumer projects are *sibling folders* to `scrapers-lib`. A typical layout:

```
Workspace/
  scrapers-lib/              <-- the library (this repo)
  demo1-pulse-check/         <-- your consumer project
    .venv/
    .env                     <-- API keys / secrets (gitignored)
    pyproject.toml
    data/
      cache/                 <-- diskcache files
      profiles/              <-- Playwright per-domain profiles
      scheduler.db           <-- Scheduler state (SQLite)
      mentions.db            <-- your persisted data (SQLite)
    src/
      anchors.py             <-- Anchor definitions
      enqueue.py             <-- what to scrape, on what cadence
      sink.py                <-- result_sink that writes to mentions.db
      run_worker.py          <-- worker entry point
```

### Install

From inside the consumer project directory:

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows; use `source .venv/bin/activate` on Unix
pip install -e ../scrapers-lib
playwright install chromium    # only needed if you use Tier 2/3 sources
```

### Environment

Copy `../scrapers-lib/.env.example` to `./.env` and fill in credentials
for the sources you use. Most sources need no credentials; see
[`README.md`](../README.md) for the current list.

---

## 3. Anchors: defining what you're tracking

An `Anchor` represents one tracked thing — a product, a game, a company,
a topic. Fetchers use anchors to *attribute* fetched content: a RawMention
or ProductSnapshot carries an `Attribution` that links it back to the
anchor it matched.

### The minimum

```python
from scrapers_lib import Anchor, AttributionRegex

alienware_m18 = Anchor(
    anchor_id="alienware_m18",
    anchor_type="product",
    name="Alienware m18",
    attribution_regex=AttributionRegex(
        primary=["Alienware m18", "m18 R2"],
    ),
)
```

That's enough for any fetcher that uses **regex-based attribution**
(RSS / article body / Reddit / YouTube / Amazon reviews / BestBuy
reviews). When the fetcher sees your regex tokens in the text, it
emits a `RawMention` attributed to this anchor.

### Adding URL-map attribution

Tier 2 and Tier 3 product-snapshot fetchers use **URL-map attribution**
instead — they match by the URL you're fetching, not by text content.
You add a `source_urls` mapping per anchor:

```python
alienware_m18 = Anchor(
    anchor_id="alienware_m18",
    anchor_type="product",
    name="Alienware m18",
    attribution_regex=AttributionRegex(primary=["Alienware m18"]),
    source_urls={
        "dell": "https://www.dell.com/en-us/shop/dell-laptops/alienware-m18/",
        "bestbuy": "https://www.bestbuy.com/site/alienware-m18/6530512.p?skuId=6530512",
        "amazon": "https://www.amazon.com/dp/B0CGXJ1234",
    },
)
```

The key on the left (`"dell"`, `"bestbuy"`, `"amazon"`) is the registered
**source name** — the same string you pass to the Scheduler as `source=`.
The right side is the exact URL the fetcher will hit.

### Refining with corroboration and exclusion

For noisy text sources (Reddit, RSS summaries), a bare primary token
can over-match. `AttributionRegex` has three knobs:

```python
AttributionRegex(
    primary=["Alienware"],
    corroboration=["m18", "18-inch", "gaming laptop"],
    exclusion=["Alienware keyboard", "Alienware mouse pad"],
)
```

Matching rules per Anchor:
- Any **exclusion** token hit → drop the anchor on this text.
- At least one **primary** token must match.
- If **corroboration** is non-empty, at least one must also match.

Tokens are literal substrings (auto-escaped) by default;
prefix with `re:` for raw regex. Case-insensitive throughout.

### Worked example: Demo 1 anchor set

Tracking Alienware vs three competitors across 4 major product lines:

```python
# anchors.py
from scrapers_lib import Anchor, AttributionRegex

ALIENWARE_M18 = Anchor(
    anchor_id="alienware_m18",
    anchor_type="product",
    name="Alienware m18",
    attribution_regex=AttributionRegex(
        primary=["Alienware m18", "m18 R2"],
        corroboration=["gaming laptop", "RTX"],
    ),
    source_urls={
        "dell": "https://www.dell.com/en-us/shop/dell-laptops/alienware-m18/",
    },
)

ROG_STRIX_G16 = Anchor(
    anchor_id="rog_strix_g16",
    anchor_type="product",
    name="ASUS ROG Strix G16",
    attribution_regex=AttributionRegex(
        primary=["ROG Strix G16", "Strix G16"],
        corroboration=["ASUS", "gaming laptop"],
    ),
    source_urls={
        "asus": "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/",
    },
)

# ... similar Anchor for Razer Blade 16, MSI Raider 18 HX, etc.

ANCHORS = [ALIENWARE_M18, ROG_STRIX_G16, ...]
```

---

## 4. Recipe: direct fetcher call + persist to SQLite

The simplest pattern — no Scheduler, just one fetch at a time.
Useful for one-shot scripts, REPL exploration, or pipelines that
already have their own concurrency layer.

```python
# quick_fetch.py
import sqlite3
from scrapers_lib.tier1.rss import fetch_rss_feed
from anchors import ANCHORS

# Fetch
mentions = fetch_rss_feed(
    "https://feeds.ign.com/ign/games-all",
    anchors=ANCHORS,
    source_slug="ign",
)

# Persist (trivial first version — see Recipe 6 for a proper sink)
conn = sqlite3.connect("data/mentions.db")
conn.execute("""
    CREATE TABLE IF NOT EXISTS mentions (
        mention_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_title TEXT,
        author TEXT,
        channel TEXT,
        published_at TEXT,
        fetched_at TEXT NOT NULL,
        raw_text TEXT NOT NULL,
        anchor_id TEXT,
        attribution_method TEXT
    )
""")
for m in mentions:
    conn.execute("""
        INSERT OR REPLACE INTO mentions VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        m.mention_id,
        m.source,
        m.source_type,
        m.source_url,
        m.source_title,
        m.author,
        m.channel,
        m.published_at.isoformat() if m.published_at else None,
        m.fetched_at.isoformat(),
        m.raw_text,
        m.attribution.anchor_id if m.attribution else None,
        m.attribution.method if m.attribution else None,
    ))
conn.commit()
conn.close()
print(f"Wrote {len(mentions)} mentions.")
```

**Why `INSERT OR REPLACE`:** `mention_id` is deterministic — the
same piece of content re-fetched later produces the same ID. Using
`OR REPLACE` (or `ON CONFLICT DO UPDATE` for richer upserts) means
your DB absorbs re-fetches cleanly. Accidentally duplicate rows are
impossible under this scheme.

---

## 5. Recipe: Scheduler with SQLite-backed sink

The production pattern for 24x7 patient scraping. Scheduler owns a
queue in its own state file; your sink owns the data.

### Sink

```python
# sink.py
import json
import sqlite3
from pathlib import Path
from scrapers_lib import RawMention, ProductSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS mentions (
    mention_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_title TEXT,
    author TEXT,
    author_id TEXT,
    channel TEXT,
    parent_id TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    anchor_id TEXT,
    attribution_method TEXT,
    attribution_confidence REAL,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_mentions_anchor ON mentions(anchor_id);
CREATE INDEX IF NOT EXISTS idx_mentions_published ON mentions(published_at);
CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source);

CREATE TABLE IF NOT EXISTS snapshots (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    variant_key TEXT,
    anchor_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    category TEXT,
    config_summary TEXT,
    price TEXT,           -- store Decimal as TEXT to preserve precision
    list_price TEXT,
    currency TEXT,
    in_stock INTEGER,
    availability_text TEXT,
    rating REAL,
    review_count INTEGER,
    image_url TEXT,
    specs_json TEXT,
    raw_json TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id, variant_key, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_anchor ON snapshots(anchor_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_fetched ON snapshots(fetched_at);
"""


class SqliteSink:
    """Callable that writes RawMention / ProductSnapshot to SQLite.

    Designed to be passed as the ``result_sink`` kwarg to ``Scheduler``.
    Opens a per-call connection to avoid cross-thread SQLite lock issues
    in case the Scheduler is ever run multi-threaded.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        # Prepare schema once at construction time.
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(SCHEMA)

    def __call__(self, results: list) -> None:
        """Scheduler calls this with a list of results from one fetch."""
        if not results:
            return
        with sqlite3.connect(self._db_path) as conn:
            for r in results:
                if isinstance(r, RawMention):
                    self._insert_mention(conn, r)
                elif isinstance(r, ProductSnapshot):
                    self._insert_snapshot(conn, r)
            conn.commit()

    @staticmethod
    def _insert_mention(conn: sqlite3.Connection, m: RawMention) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO mentions VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m.mention_id,
                m.source,
                m.source_type,
                m.source_url,
                m.source_title,
                m.author,
                m.author_id,
                m.channel,
                m.parent_id,
                m.published_at.isoformat() if m.published_at else None,
                m.fetched_at.isoformat(),
                m.raw_text,
                m.attribution.anchor_id if m.attribution else None,
                m.attribution.method if m.attribution else None,
                m.attribution.confidence if m.attribution else None,
                json.dumps(m.raw) if m.raw else None,
            ),
        )

    @staticmethod
    def _insert_snapshot(conn: sqlite3.Connection, s: ProductSnapshot) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO snapshots VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.source,
                s.source_id,
                s.variant_key or "",    # PK component can't be NULL
                s.anchor_id,
                s.url,
                s.title,
                s.brand,
                s.model,
                s.category,
                s.config_summary,
                str(s.price) if s.price is not None else None,
                str(s.list_price) if s.list_price is not None else None,
                s.currency,
                int(s.in_stock) if s.in_stock is not None else None,
                s.availability_text,
                s.rating,
                s.review_count,
                s.image_url,
                json.dumps(s.specs) if s.specs else None,
                json.dumps(s.raw) if s.raw else None,
                s.fetched_at.isoformat(),
            ),
        )
```

### Worker entry point

```python
# run_worker.py
from scrapers_lib import Scheduler
from scrapers_lib.core.rate_limiter import RateLimiter
from scrapers_lib.core.robots import RobotsChecker
from scrapers_lib.core.logging_config import configure_logging

# IMPORTANT: import every fetcher module you use so they register.
from scrapers_lib.tier1 import article, reddit, rss, youtube  # noqa: F401
from scrapers_lib.tier2 import acer, asus, dell, hp, lenovo, msi  # noqa: F401
from scrapers_lib.tier3 import amazon, bestbuy  # noqa: F401

from sink import SqliteSink

configure_logging(level="INFO", per_module={
    "scrapers_lib.core.scheduler": "INFO",
    "scrapers_lib.tier3": "DEBUG",  # verbose on fragile sources
})

rate_limiter = RateLimiter(default_rps=0.5, default_burst=1)
# Per-domain tuning — patient with known-fragile hosts, looser on APIs.
rate_limiter.configure("www.dell.com", rps=0.2, burst=1)
rate_limiter.configure("www.bestbuy.com", rps=0.25, burst=1)
rate_limiter.configure("feeds.ign.com", rps=2.0, burst=3)

robots = RobotsChecker(user_agent="my-demo1-pulse-check/0.1")
sink = SqliteSink("data/mentions.db")

with Scheduler(
    state_file="data/scheduler.db",
    result_sink=sink,
    rate_limiter=rate_limiter,
    robots=robots,
    poll_interval=5.0,
    default_max_attempts=3,
) as sched:
    # Enqueue happens elsewhere (see Recipe 7). Here we just drain.
    sched.run_worker(mode="forever")
```

### Enqueue script (run on a schedule from Task Scheduler / cron)

```python
# enqueue.py
from scrapers_lib import Scheduler
from scrapers_lib.core.rate_limiter import RateLimiter
from scrapers_lib.core.robots import RobotsChecker

from anchors import ALIENWARE_M18, ROG_STRIX_G16, ANCHORS
from sink import SqliteSink

sink = SqliteSink("data/mentions.db")  # not used in enqueue, but Scheduler requires it

with Scheduler(
    state_file="data/scheduler.db",
    result_sink=sink,
    rate_limiter=RateLimiter(default_rps=0.5),
    robots=RobotsChecker(user_agent="my-demo1-pulse-check/0.1"),
) as sched:
    # Tier 1 — discovery mode across many feeds
    for feed_url, slug in [
        ("https://feeds.ign.com/ign/games-all", "ign"),
        ("https://www.gamespot.com/feeds/mashup/", "gamespot"),
        # ...
    ]:
        sched.enqueue(feed_url, source="rss", anchors=None, source_slug=slug)

    # Reddit discovery mode across relevant subs
    for sub in ["r/gaminglaptops", "r/Alienware", "r/ASUSROG"]:
        sched.enqueue(sub, source="reddit", anchors=None, limit=50)

    # Tier 2/3 — anchor-driven, one job per (anchor, source)
    for anchor in ANCHORS:
        for source, url in anchor.source_urls.items():
            sched.enqueue(url, source=source, anchors=[anchor])

    print(f"Queued. Stats: {sched.stats()['status_counts']}")
```

Run `enqueue.py` once a day (or whenever), and `run_worker.py`
continuously. The Scheduler's SQLite state dedupes and paces.

---

## 6. Recipe: monitoring Scheduler

```python
from scrapers_lib import Scheduler
# ... setup omitted

with Scheduler(...) as sched:
    stats = sched.stats()

print(f"Jobs by status: {stats['status_counts']}")
# -> {'done': 420, 'pending': 17, 'in_progress': 0, 'failed': 3}

print(f"Domain health:")
for domain, state in stats["domains"].items():
    backoff = state["backoff_until"]
    cf = state["consecutive_failures"]
    print(f"  {domain}: {state['total_successes']} ok, "
          f"{state['total_failures']} fail, "
          f"consecutive_failures={cf}, "
          f"under_backoff={backoff is not None}")
```

**What to watch for:**

- `failed` climbing without `done` increasing → a registered source's URL format may have changed; re-run its probe script.
- `consecutive_failures` on a domain → library will back off that domain; expected for transient flaps.
- `backoff_until` set → the Scheduler has temporarily paused that domain. Check logs for the triggering error.

---

## 7. Recipe: handling errors

The Scheduler absorbs most errors internally (retries per-job,
backs off per-domain). You usually don't need explicit handling in
the sink. But two cases benefit from awareness:

### `BlockedError` from a fetcher

```python
from scrapers_lib import BlockedError

# BlockedError is raised by fetchers when the site is clearly refusing
# (429, 403 with Akamai signatures, CAPTCHA page, etc.). The Scheduler
# catches it and applies a *longer* domain-wide backoff than normal
# retry backoff — typically 6 hours.
#
# You, the consumer, never see BlockedError directly unless you're
# calling fetchers without the Scheduler. If you ARE calling directly:

try:
    reviews = fetch_bestbuy_reviews(url, anchors=anchors)
except BlockedError:
    # Site is explicitly refusing. Don't retry immediately.
    # Wait hours, not seconds.
    pass
```

### Malformed anchor / missing URL-map entry

```python
try:
    snapshot = fetch_dell_product(url, anchors=[anchor])
except ValueError as e:
    # Raised by URL-map attribution when no anchor has
    # source_urls["dell"] == url. Fix the anchor; the URL must match
    # exactly (trailing slash, query string, fragment all count).
    print(f"Attribution error: {e}")
```

### Fetcher returns empty list

This is **not** an error — it's partial success. Several fetchers
return `[]` when they legitimately found no content:

- `article` — paywall, body too short, 404 page.
- `youtube` — video has no captions.
- `rss` — feed was fetched but had no new entries matching anchors.

Your sink's `len(results) == 0` branch should be a no-op, not an alert.

---

## 8. Recipe: refresh cadences per source

Different sources deserve different update frequencies. The Scheduler
has no built-in cron — you control cadence by *when and what you
enqueue*. Two idiomatic patterns:

### Pattern A: enqueue from a cron job

Run your `enqueue.py` (see Recipe 5) on a schedule via Windows Task
Scheduler or cron:

```
Daily 3 AM — enqueue product snapshots (prices move slowly)
Every 4 hours — enqueue feed + subreddit mentions (fresh content)
Weekly Sunday — enqueue all review fetches (long-tail data)
```

The worker loop runs continuously and drains whatever you've queued.

### Pattern B: enqueue on success inside the sink

Less common but useful for follow-up fetches (e.g., "when an RSS
entry looks interesting, enqueue its full article body"):

```python
class EnrichingSink:
    def __init__(self, db_path, sched):
        self._db = SqliteSink(db_path)
        self._sched = sched

    def __call__(self, results):
        self._db(results)
        # Follow-up: enqueue article body fetches for high-engagement RSS entries
        for m in results:
            if isinstance(m, RawMention) and m.source == "ign":
                if self._is_interesting(m):
                    self._sched.enqueue(
                        m.source_url, source="article",
                        anchors=[...], source_slug="ign",
                    )
```

---

## 9. Data shape quick reference

What each registered source actually returns, by shape. Use this to
design downstream tables / analysis. For full field-by-field detail,
see [`ARCHITECTURE.md`](ARCHITECTURE.md) §11.

### Tier 1

| Source | Return | Notes |
|---|---|---|
| `rss` | `list[RawMention]` | One per feed entry. Discovery or anchor mode. `source` = your `source_slug`. Has `author`, `channel`, `published_at`. |
| `article` | `list[RawMention]` | Full body via trafilatura. Fetched through `warmed_curl_session()` (Chrome impersonation + HTTP/1.1) since v1.4.0, so Cloudflare-fronted reviewer sites (notebookcheck and similar) now work. `source` = your `source_slug`. Returns `[]` on paywall / short body. |
| `reddit` | `list[RawMention]` | `source_type="post"`. `channel="r/<sub>"`. `raw.score`, `raw.num_comments` present. |
| `reddit_comments` | `list[RawMention]` | Post first + comment tree. `source_type="post"` or `"comment"`. `parent_id=t3_<post_id>`. |
| `youtube` | `list[RawMention]` | `source_type="transcript_chunk"`. `source_url` deep-linked with `&t=<s>s`. No `author` / `channel` / `published_at` (would need YouTube Data API). |
| `bestbuy_api` | `list[ProductSnapshot]` | Developer API fetcher. Requires `BESTBUY_API_KEY`. Indefinitely dormant without credential. |

### Tier 2 — manufacturer spec pages (all return `list[ProductSnapshot]`)

| Source | Notes |
|---|---|
| `dell` | Alienware + XPS. Playwright + stealth + warming. ~20 spec categories per tile. |
| `hp` | Shop PDPs. curl_cffi + warmed session → ~23-26 categories per tile (config-picker + async GraphQL Tech Specs, Wave 2e). Async fetch is best-effort with fallback to ~12-category config-picker-only data. |
| `lenovo` | PSREF spec reference. No prices. ~50 features across 8 categories. |
| `asus` | Host-dispatched. `rog.asus.com` → ROG SSR spec sections (20+ categories). `www.asus.com` → Zenbook / Vivobook / TUF Gaming via Nuxt JS state (22-28 categories). Both share `SOURCE = "asus"`. No prices. |
| `acer` | `acer.com` PDP. Plain httpx + 13 SSR `<table>` blocks. ~60+ spec keys per `/pdp/<SKU>` URL. Per-SKU granularity. JSON-LD enrichment for title/brand/image/price/availability. |
| `msi` | `us.msi.com` (Akamai-gated). curl_cffi + warmed session. `/Specification` is universal (gaming + AI/Stealth lines), 27-31 spec rows column-per-SKU; main-page JSON-LD `ItemList` fallback (~11 fields). One snapshot per `<thead>` SKU column. No prices. |

### Tier 3 — retailer scraping (fragile by design)

| Source | Return | Notes |
|---|---|---|
| `amazon` | `list[ProductSnapshot]` | PDP scrape. Price, rating, specs from product detail tables. |
| `amazon_reviews` | `list[RawMention]` | Up to ~10 reviews from PDP inline. Full reviews page blocked (sign-in wall). |
| `bestbuy_reviews` | `list[RawMention]` | Default: 5 reviews from PDP inline. `paginate=True`: walks all pages with `published_at`, `verified_purchase`, `helpful_count`, `ownership_duration`. |

---

## 10. FAQ / gotchas

**Q: Do I need to call `configure_logging`?**
No — the library never configures root logging itself. If you skip,
library logs silently discard. Call `configure_logging(level="INFO")`
once at startup if you want to see them.

**Q: Why does `fetch_reddit_listing` take `r/Games` as the URL?**
It accepts several shorthands (`r/Games`, bare `Games`, full URL,
`t3_<id>` fullnames). Any of them work.

**Q: The Scheduler failed to enqueue a job; `fetch_options` aren't being
accepted.**
`Scheduler.enqueue(**fetch_options)` serializes kwargs as JSON for
state-file persistence. Only JSON-serializable values work — `Path`
objects, sets, custom classes will error. Use `str(my_path)`.

**Q: `BESTBUY_API_KEY` isn't set and I haven't used `bestbuy_api`;
can I safely ignore the env var?**
Yes. Each fetcher only reads the credentials it needs.
`bestbuy_api` raises a `RuntimeError` only when invoked without the key.

**Q: I see `ERR_HTTP2_PROTOCOL_ERROR` in logs for BestBuy / HP.**
Those are Akamai-protected Tier 3 / Tier 2 sources. The fetchers
handle the bypass internally (curl_cffi + HTTP/1.1 for BestBuy;
Playwright + stealth for Dell). The error messages come from
*probe* attempts, not the main path. Check that your fetch actually
returned data before worrying.

**Q: My Scheduler state file is corrupt after a crash.**
Delete `data/scheduler.db`. The Scheduler rebuilds on next run;
you'll lose in-progress queue state but your persisted `mentions.db`
is untouched.

**Q: Can two workers run against the same state file?**
No. The Scheduler is single-process by design. Run one worker;
scale by enqueueing more or tuning rate limiter per-domain.

**Q: How do I test my consumer project without hitting real sites?**
Import a fetcher's `parse_*` function directly (e.g.,
`parse_rss_feed`, `parse_dell_product_page`) and pass it canned
HTML / JSON. Every fetcher has a pure-parse function for this reason.

**Q: A site changed its structure; my fetcher returns `[]`.**
Re-run the relevant `scripts/<source>/probe_*.py` — it captures a
fresh fixture and reports current DOM shape. File an issue (or fix)
on the library side; your consumer is not at fault.

---

## 11. Wiring it up — 24x7 on Windows

See [`README.md`](../README.md) § "Running the worker 24x7 on Windows"
for the Task Scheduler wiring. That covers `.bat` wrapping, trigger
configuration, restart-on-failure, and logging redirection. Nothing
in this guide duplicates that setup.
