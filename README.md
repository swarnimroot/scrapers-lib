# scrapers-lib

**Status:** draft &nbsp;·&nbsp; **Library version:** 0.4.0 (pre-release)

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

## Running the worker 24x7 on Windows (Task Scheduler)

The Scheduler is designed to run patiently for days at a stretch on a
personal laptop. Windows Task Scheduler handles the "keep it running,
restart on failure, start at logon" lifecycle without any service layer.

Minimal setup, assuming your consumer project has a `run_worker.py`
that calls `Scheduler(...).run(mode="forever")`:

1. **Wrap the run in a `.bat` file** so Task Scheduler has something
   to execute. Save as `run_worker.bat` next to your consumer project:

   ```bat
   @echo off
   cd /d C:\path\to\your-consumer-project
   call .venv\Scripts\activate.bat
   python run_worker.py
   ```

2. **Open Task Scheduler** (`taskschd.msc`) → **Create Task...** (not
   "Create Basic Task" — you want the full editor).

3. **General** tab:
   - Name: `scrapers-lib worker`
   - "Run whether user is logged on or not" — **off** for a personal
     laptop; **on** if you want it running while locked (requires
     storing your password).
   - "Run with highest privileges" — **off** (Playwright does not
     need elevation; scraping should run as a normal user).

4. **Triggers** tab → **New...**:
   - Begin the task: **At log on** (any user, or restrict to yours).
   - Advanced → "Repeat task every" — leave unchecked; the worker's
     own loop handles repetition.

5. **Actions** tab → **New...**:
   - Action: **Start a program**.
   - Program/script: the full path to `run_worker.bat`.
   - Start in: the consumer project folder (same folder as the
     `.bat` — needed so relative paths resolve).

6. **Conditions** tab:
   - "Start the task only if the computer is on AC power" — **off**
     if you want the worker to run on battery too.
   - "Wake the computer to run this task" — **off** unless you have
     a reason.

7. **Settings** tab:
   - "Allow task to be run on demand" — on (lets you right-click →
     Run to test).
   - "If the task fails, restart every" — 5 minutes, up to 3 times
     (the Scheduler's own backoff handles per-domain failures; this
     guards against worker-process crashes).
   - "Stop the task if it runs longer than" — **unchecked** (the
     worker is designed to run indefinitely).

8. **Save**. You will be prompted for your Windows password if you
   chose "run whether logged on or not".

Logs: the worker writes to `stderr` by default. To capture them to a
file, redirect in your `.bat`:

```bat
python run_worker.py 1>> worker.log 2>&1
```

or configure Python's `logging` to a rotating file handler inside
your consumer project.

To check the worker is alive: `Get-Process python` in PowerShell, or
`tasklist /fi "imagename eq python.exe"` in cmd. To stop: right-click
the task → **End**, or `taskkill /f /im python.exe` (indiscriminate).

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
- [`docs/ADDING_A_SOURCE.md`](docs/ADDING_A_SOURCE.md) — methodology for adding a new Tier 2 fetcher: reconnaissance techniques, per-manufacturer pattern catalog, decision tree, worked case studies

## Consumers

scrapers-lib is intended to be used by consumer projects in sibling folders. Each consumer has its own README, config, and data store. The library stays demo-agnostic.

## Responsible use

You are responsible for respecting the terms of service of the sources you fetch from. The library defaults to respecting `robots.txt` and enforces patient pacing; override only with good reason. Use for personal research and reasonable commercial use; do not use to overwhelm sites or circumvent explicit bans.

## License

MIT — see [`LICENSE`](LICENSE).
