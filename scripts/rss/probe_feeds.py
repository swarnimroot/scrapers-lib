"""RSS / Atom feed discovery for Demo 3's 13-site gaming-news catalog.

For each site, tries a small list of candidate URLs (WordPress default,
Ghost default, known-custom paths) and reports which ones respond with
a parseable feed. Output is a proposed feed-URL mapping for user review
before `tier1/rss.py` is written.

Run from the repo root::

    .venv/Scripts/python.exe scripts/rss/probe_feeds.py

No fixtures saved (feeds are tiny and consumer-configured, not committed
as test fixtures in this probe layer; the RSS fetcher's tests get their
own small fixtures later).
"""

from __future__ import annotations

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Per-site candidate feed URLs, highest-confidence first.
CANDIDATES: dict[str, list[str]] = {
    "IGN": [
        "https://feeds.ign.com/ign/all",
        "https://feeds.ign.com/ign/games-all",
        "https://www.ign.com/rss",
    ],
    "GameSpot": [
        "https://www.gamespot.com/feeds/mashup/",
        "https://www.gamespot.com/feeds/news/",
        "https://www.gamespot.com/feeds/reviews/",
    ],
    "Polygon": [
        "https://www.polygon.com/rss/index.xml",
        "https://www.polygon.com/rss/front/index.xml",
        "https://www.polygon.com/feed",
    ],
    "PCGamer": [
        "https://www.pcgamer.com/rss/",
        "https://www.pcgamer.com/feed/",
        "https://www.pcgamer.com/rss",
    ],
    "Kotaku": [
        "https://kotaku.com/rss",
        "https://kotaku.com/feed",
        "https://kotaku.com/feed/",
    ],
    "Eurogamer": [
        "https://www.eurogamer.net/?format=rss",
        "https://www.eurogamer.net/feed",
        "https://www.eurogamer.net/rss",
    ],
    "GameInformer": [
        "https://www.gameinformer.com/rss.xml",
        "https://www.gameinformer.com/feed",
        "https://www.gameinformer.com/b/MainFeed.aspx",
    ],
    "GamesBeat (VentureBeat)": [
        "https://venturebeat.com/category/games/feed/",
        "https://venturebeat.com/feed/",
    ],
    "GamesIndustry.biz": [
        "https://www.gamesindustry.biz/feed",
        "https://www.gamesindustry.biz/rss",
        "https://www.gamesindustry.biz/feed/news",
    ],
    "GameDeveloper.com": [
        "https://www.gamedeveloper.com/rss.xml",
        "https://www.gamedeveloper.com/feed",
        "https://www.gamedeveloper.com/rss",
    ],
    "RockPaperShotgun": [
        "https://www.rockpapershotgun.com/feed",
        "https://www.rockpapershotgun.com/feed/",
        "https://www.rockpapershotgun.com/rss",
    ],
    "VG247": [
        "https://www.vg247.com/feed",
        "https://www.vg247.com/feed/",
        "https://www.vg247.com/rss",
    ],
    "TheGamer": [
        "https://www.thegamer.com/feed/",
        "https://www.thegamer.com/rss",
        "https://www.thegamer.com/feed",
    ],
}


def looks_like_feed(body: str, content_type: str) -> tuple[bool, str]:
    """Return (is_feed, flavor). Flavor is 'rss' / 'atom' / 'unknown'."""
    ct = (content_type or "").lower()
    head = body[:2000].lower()
    if "<rss" in head:
        return True, "rss"
    if "<feed" in head and "xmlns" in head and "atom" in head:
        return True, "atom"
    if "<feed" in head and "xmlns=\"http://www.w3.org/2005/atom\"" in head:
        return True, "atom"
    # Some feeds omit xmlns declaration visibility in first 2000 chars
    if "<channel>" in head:
        return True, "rss"
    return False, "unknown"


def count_items(body: str, flavor: str) -> int:
    """Count entries in the body — RSS <item>, Atom <entry>."""
    if flavor == "rss":
        return body.count("<item")
    if flavor == "atom":
        return body.count("<entry")
    return 0


def probe_one(url: str) -> dict:
    try:
        r = httpx.get(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
            follow_redirects=True,
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        return {"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}"}

    is_feed = False
    flavor = "unknown"
    items = 0
    if r.status_code == 200:
        is_feed, flavor = looks_like_feed(r.text, r.headers.get("content-type", ""))
        if is_feed:
            items = count_items(r.text, flavor)

    return {
        "url": url,
        "final_url": str(r.url),
        "status": r.status_code,
        "content_type": r.headers.get("content-type", "(unset)"),
        "bytes": len(r.content),
        "is_feed": is_feed,
        "flavor": flavor,
        "items": items,
    }


def main() -> int:
    print(f"Probing {len(CANDIDATES)} sites, {sum(len(v) for v in CANDIDATES.values())} total candidate URLs\n")
    for site, urls in CANDIDATES.items():
        print(f"=== {site} ===")
        any_ok = False
        for url in urls:
            r = probe_one(url)
            if r.get("error"):
                print(f"  [x] {r['url']}  ERROR: {r['error']}")
                continue
            status = r["status"]
            if status != 200:
                print(f"  [x] {r['url']}  HTTP {status}")
                continue
            if not r["is_feed"]:
                print(
                    f"  [?] {r['url']}  200 OK but not a feed (ct={r['content_type']}, "
                    f"{r['bytes']:,}b)"
                )
                continue
            final_suffix = (
                f"  -&gt; {r['final_url']}" if r['final_url'] != r['url'] else ""
            )
            print(
                f"  [OK] {r['url']}  {r['flavor']}, {r['items']} items, "
                f"{r['bytes']:,}b{final_suffix}"
            )
            any_ok = True
        if not any_ok:
            print(f"  !! no working feed found — may need manual discovery")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
