# scrapers-lib

**Status:** draft &nbsp;·&nbsp; **Library version:** 0.1.0 (pre-release)

A reusable Python library for fetching, normalizing, and attributing data from multiple web sources — community posts, product pages, news articles, video transcripts — into consistent schemas that any Python project can consume.

Not an application. No database, no UI, no LLM. Just fetchers and normalization primitives plus a persistent Scheduler for running patient scrapers 24x7.

---

## What it's good for

- Tracking specific products, topics, games, or companies across many sources with one API shape.
- Building a normalized corpus of community commentary attributed to the things you care about.
- Running a long, patient scraper overnight without babysitting it.

## What it doesn't do

- Store data permanently (the library returns data; the consumer saves it).
- Analyze, summarize, or visualize (that is your project's job).
- Pay for proxies or scraping services (free tiers only).
- Guarantee 100% coverage of fragile sources (Tier 3 scraping is honestly imperfect).

## Install

Prerequisites: **Python 3.12** and, on Windows, git-bash or PowerShell.

```bash
# From inside the scrapers-lib/ folder:
pip install -e .

# Install Playwright browsers (needed for Tier 2/3 sources):
playwright install chromium

# Copy the example env and fill in credentials for the sources you use:
cp .env.example .env
```

## Credentials

Not every source needs credentials. The library only reads the env vars for sources you use.

| Source | Env vars | How to get |
|---|---|---|
| Reddit (PRAW) | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | Create a *script*-type app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) — free, ~3 min |
| BestBuy Developer API | `BESTBUY_API_KEY` | Apply at [bestbuyapis.github.io](https://bestbuyapis.github.io/) — free; approval usually within a week |
| YouTube transcripts | none | `youtube-transcript-api` uses no auth |
| RSS feeds | none | public feeds |
| Manufacturer sites (Tier 2) | none | public pages |
| Amazon, BestBuy reviews (Tier 3) | none | public pages; fragile by design |

## Quickstart

Fetch items from an RSS feed, attribute them to a topic, print them:

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

for m in mentions:
    print(m.published_at, m.source_title, m.source_url)
```

For long-running, patient scraping across many URLs, use `Scheduler` — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §5.2.

## Repository layout

- `scrapers_lib/core/` — schemas, attribution, caching, rate limiting, HTTP, Playwright, Scheduler
- `scrapers_lib/tier1/` — reliable API/feed sources
- `scrapers_lib/tier2/` — manufacturer pages (JS-heavy, moderate reliability)
- `scrapers_lib/tier3/` — retailer scraping (fragile)
- `tests/` — unit tests (fast, offline) and integration tests (gated by `SCRAPERSLIB_LIVE_TESTS=1`)
- `docs/` — PRD, Architecture, Tasks

## Documentation

- [`docs/PRD.md`](docs/PRD.md) — what this library is, what it's for, what it's not
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design details: schemas, Scheduler, per-source coverage
- [`docs/TASKS.md`](docs/TASKS.md) — roadmap grouped by implementation wave

## Consumers

scrapers-lib is intended to be used by consumer projects in sibling folders. Each consumer has its own README, config, and data store. The library stays demo-agnostic.

## Responsible use

You are responsible for respecting the terms of service of the sources you fetch from. The library defaults to respecting `robots.txt` and enforces patient pacing; override only with good reason. Use for personal research and reasonable commercial use; do not use to overwhelm sites or circumvent explicit bans.

## License

MIT — see [`LICENSE`](LICENSE).
