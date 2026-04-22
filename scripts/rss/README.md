# scripts/rss/

RSS / Atom feed-discovery tooling for Demo 3's gaming-news catalog.

Because `tier1/rss.py` is a universal RSS fetcher (it consumes any
feed), the per-site feed URLs are consumer-project configuration, not
library code. This script exists to discover working feed URLs when
adding sites to a consumer catalog.

## The script

| Script | What it does | Network |
|---|---|---|
| `probe_feeds.py` | Tries 2–4 candidate URLs per site, reports which ones return a parseable RSS/Atom feed and how many items each has. Re-run whenever a site redesigns and its committed feed URL breaks. | yes |

## Running

```bash
.venv/Scripts/python.exe scripts/rss/probe_feeds.py
```

Output is a human-readable summary per site (marked `[OK]` / `[x]` / `[?]`).
No fixtures saved — RSS content changes hourly and is never committed
as test data at this layer; `tier1/rss.py` unit tests use small
synthetic fixtures committed under `tests/tier1/fixtures/rss/`.

## Demo 3 feed catalog (confirmed 2026-04-22)

Discovered by running `probe_feeds.py` against the 13-site user-
confirmed list. Items-per-fetch is a rough guide to how often each
feed needs polling to avoid missing entries.

| Site | Canonical feed URL | Items/fetch | Notes |
|---|---|---:|---|
| IGN | `feeds.ign.com/ign/games-all` | 20 | Games subset, not site-wide |
| GameSpot | `gamespot.com/feeds/news/` | 30 | News-only (vs mashup/reviews) |
| Polygon | `polygon.com/feed/` | 10 | Small feed, poll more often |
| PCGamer | `pcgamer.com/rss` | 50 | Summaries; follow-up body fetch via `tier1/article` |
| Kotaku | `kotaku.com/rss` | 20 | Canonical path (others redirect) |
| Eurogamer | `eurogamer.net/feed` | 100 | Richest feed in the catalog |
| GameInformer | `gameinformer.com/rss.xml` | 50 | Only working path |
| GamesBeat (VentureBeat) | `venturebeat.com/feed/` | 7 | Mixed (AI / startups / gaming) — games-only subpath returns 403 |
| GamesIndustry.biz | `gamesindustry.biz/feed/news` | 100 | News-only (vs `/feed` all) |
| GameDeveloper | `gamedeveloper.com/rss.xml` | 50 | Only working path |
| RockPaperShotgun | `rockpapershotgun.com/feed` | 100 | Rich feed |
| VG247 | `vg247.com/feed` | 100 | Rich feed |
| TheGamer | `thegamer.com/feed/` | 10 | Small feed |

Total ~700 items per full refresh across the 12 gaming-focused feeds
plus whatever mix VentureBeat's site-wide feed carries.

## Why VentureBeat stays despite the 403

VentureBeat's `category/games/feed/` returns HTTP 403 to bot clients
(plain httpx with a current Chrome UA). Their site-wide `/feed/` works
but carries AI / startup / enterprise articles alongside occasional
games coverage. User decision 2026-04-22: keep it in the catalog and
let all content flow through (Demo 3's discovery-driven mode slices
by anchor at the consumer layer, so the non-gaming noise is not a
pipeline problem).
