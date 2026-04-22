"""BestBuy reviews-page pagination reconnaissance — Wave 2d.

Hits ``bestbuy.com/site/reviews/name/<SKU>?page=N`` for a small N to
establish what Wave 2d is building against. Uses the same bypass
primitive as ``tier3/bestbuy.py``: curl_cffi with Chrome TLS
impersonation forced onto HTTP/1.1 plus a homepage warm-up (Akamai's
HTTP/2 bot gate is the same on this surface as on ``/site/<slug>.p``).

Questions this probe answers, mapped to ``docs/ADDING_A_SOURCE.md``:

- §3.8 — Is the ``/site/reviews/name/`` surface behind the same
  Akamai gate as the PDP? If yes, curl_cffi + HTTP/1.1 works.
- §3.3 / §3.4 — Is review content SSR'd as HTML (DOM nodes with
  review bodies / ratings / dates) or as JSON-LD? What's the review
  container selector?
- Wave-2d-specific — What is the pagination mechanic? ``?page=N``,
  ``?offset=X&count=Y``, next-link? What's the end-of-data signal
  (empty review list / 404 / redirect / marker)? How many reviews
  per page? Are ``datePublished`` values present (they're absent on
  the PDP's JSON-LD — that's the primary reason Wave 2d exists)?
- Bonus — Are there per-review permalinks? Helpful-vote counts?
  Verified-purchaser tags? Star-rating format?

Output (under ``tests/tier3/fixtures/bestbuy/``):

- ``reviews_<SKU>_page<N>.html`` — raw response body.
- ``reviews_<SKU>_page<N>_status<code>.html`` on non-200.

Run from the repo root::

    .venv/Scripts/python.exe scripts/bestbuy/probe_reviews_pagination.py [SKU] [MAX_PAGES]

Defaults: SKU=6628371 (Alienware m18 — already present as
``pdp_6628371.html`` fixture, known to return real HTML via the
Wave 2c curl_cffi path), MAX_PAGES=3. Three pages is enough to
confirm pagination shape + end-of-data behavior without stressing
Akamai. Probe pace: 3 s sleep between page fetches + the standard
1 s post-warm pause.

See ``docs/ADDING_A_SOURCE.md`` §3 (techniques) and §5 (decision
tree). This probe is the Wave 2d counterpart to Wave 2c's
``probe_posture.py``.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier3" / "fixtures" / "bestbuy"

HOME_URL = "https://www.bestbuy.com/"
REVIEWS_URL_TEMPLATE = "https://www.bestbuy.com/site/reviews/name/{sku}?page={page}"

DEFAULT_SKU = "6628371"
DEFAULT_MAX_PAGES = 3
PAGE_DELAY_SECONDS = 3.0
WARM_DELAY_SECONDS = 1.0

BLOCK_MARKERS = [
    ("access denied", re.compile(r"<title>[^<]*access denied", re.I)),
    ("pardon interrupt", re.compile(r"pardon our interruption", re.I)),
    ("akamai edge", re.compile(r"errors\.edgesuite", re.I)),
    ("akamai reference", re.compile(r"reference\s*#[0-9a-f.]+", re.I)),
    ("bot challenge", re.compile(r"are you a robot|prove you are human", re.I)),
    ("captcha form", re.compile(r'action="[^"]*/captcha/', re.I)),
]

# Signals that might reveal how reviews are rendered on this surface.
REVIEW_DOM_SIGNALS = [
    ("'data-ugc' attrs", re.compile(r'data-ugc="')),
    ("'review-item' occurrences", re.compile(r"review-item", re.I)),
    ("'user-review' occurrences", re.compile(r"user-review", re.I)),
    ("'itemprop=\"review\"'", re.compile(r'itemprop="review"')),
    ("'data-track=\"Review'", re.compile(r'data-track="Review')),
    ("'\"reviewBody\"' (JSON)", re.compile(r'"reviewBody"')),
    ("'star-rating'", re.compile(r"star-rating", re.I)),
    ("'review-title'", re.compile(r"review-title", re.I)),
    ("'datePublished'", re.compile(r"datePublished", re.I)),
    ("ISO date yyyy-mm-dd", re.compile(r"\d{4}-\d{2}-\d{2}")),
    ("'helpful' vote markers", re.compile(r"helpful[^<]*vote", re.I)),
    ("'verified-purchaser'", re.compile(r"verified[- ]purchas", re.I)),
]

# Pagination signals.
PAGINATION_SIGNALS = [
    ("rel=\"next\" link", re.compile(r'rel="next"', re.I)),
    ("aria-label 'Next'", re.compile(r'aria-label="(?:Next|Go to next)', re.I)),
    ("'page=2' / 'page=3' anchors", re.compile(r'[?&]page=[2-9]')),
    ("'showing N of M' text", re.compile(r"showing[^<]*\bof\b[^<]*reviews?", re.I)),
    ("'no reviews' / 'no results' text", re.compile(r"no (?:matching\s+)?reviews|no results", re.I)),
]


def block_hits(html: str) -> list[str]:
    return [name for name, pat in BLOCK_MARKERS if pat.search(html)]


def analyze(html: str, label: str) -> dict[str, int]:
    """Run all signal regexes against html; print and return counts."""
    print(f"\n----- analyze: {label} -----")
    print(f"size: {len(html):,} chars")

    blocks = block_hits(html)
    print(f"block markers: {blocks or 'none'}")

    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"<title>: {m.group(1).strip() if m else '(none)'}")

    dom_counts: dict[str, int] = {}
    print("\n[review DOM / JSON signals]")
    for name, pat in REVIEW_DOM_SIGNALS:
        count = len(pat.findall(html))
        dom_counts[name] = count
        print(f"  {name}: {count}")

    pag_counts: dict[str, int] = {}
    print("\n[pagination signals]")
    for name, pat in PAGINATION_SIGNALS:
        count = len(pat.findall(html))
        pag_counts[name] = count
        print(f"  {name}: {count}")

    # Canary extracts: first 3 date-looking strings + first review-title-looking
    # blob + a sample of matched date contexts (helps read the fixture later).
    date_matches = re.findall(
        r"(?:datePublished|date-published|review-date)[^<>\"']{0,40}",
        html,
        re.I,
    )
    if date_matches:
        print("\n[date-context samples (up to 3)]")
        for s in date_matches[:3]:
            print(f"  {s!r}")

    return {**dom_counts, **pag_counts, "_blocks": len(blocks)}


def fetch_page(session, url: str, timeout: float = 30.0):
    """GET ``url`` via the shared curl_cffi session. Returns the response."""
    return session.get(url, timeout=timeout)


def main(argv: list[str]) -> int:
    sku = argv[1] if len(argv) > 1 else DEFAULT_SKU
    max_pages = int(argv[2]) if len(argv) > 2 else DEFAULT_MAX_PAGES

    if not sku.isdigit() or len(sku) != 7:
        print(f"ERROR: SKU must be 7 digits (got {sku!r})")
        return 2

    FIX.mkdir(parents=True, exist_ok=True)

    # Lazy import — curl_cffi is already in the dep set but keeping the probe
    # script style consistent with the library's lazy-import posture.
    from curl_cffi import CurlHttpVersion, requests  # noqa: I001

    print(f"Probe: SKU={sku} MAX_PAGES={max_pages}")
    print(f"Session: curl_cffi impersonate=chrome http_version=V1_1 (HTTP/1.1)")

    per_page_counts: dict[int, dict[str, int]] = {}

    with requests.Session(
        impersonate="chrome",
        http_version=CurlHttpVersion.V1_1,
    ) as s:
        print(f"\n[warm] GET {HOME_URL}")
        try:
            warm_resp = s.get(HOME_URL, timeout=30.0)
            print(f"  status={warm_resp.status_code} size={len(warm_resp.content):,} bytes")
        except Exception as e:
            print(f"  warm failed: {type(e).__name__}: {e}")
            print("  continuing anyway — first page fetch will reveal whether bypass works.")

        time.sleep(WARM_DELAY_SECONDS)

        for page in range(1, max_pages + 1):
            url = REVIEWS_URL_TEMPLATE.format(sku=sku, page=page)
            print(f"\n[GET page {page}] {url}")
            try:
                resp = fetch_page(s, url)
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                return 2

            status = resp.status_code
            final_url = resp.url
            ctype = resp.headers.get("content-type", "(unset)")
            print(f"  status={status} final_url={final_url}")
            print(f"  content-type={ctype} body={len(resp.content):,} bytes")

            # Save fixture
            suffix = "" if status == 200 else f"_status{status}"
            out = FIX / f"reviews_{sku}_page{page}{suffix}.html"
            out.write_bytes(resp.content)
            print(f"  saved: {out.relative_to(REPO)}")

            if status != 200:
                print(
                    f"  non-200 at page {page}; this may be the end-of-data "
                    f"signal (404) or a block. Not walking further."
                )
                # Still analyze the body for block markers / redirect hints.
                try:
                    per_page_counts[page] = analyze(resp.text, label=f"page {page} (status {status})")
                except Exception:
                    pass
                break

            try:
                html = resp.text
            except Exception as e:
                print(f"  body decode failed: {e}")
                break

            per_page_counts[page] = analyze(html, label=f"page {page}")

            # Politeness
            if page < max_pages:
                time.sleep(PAGE_DELAY_SECONDS)

    # Cross-page summary
    print("\n=== cross-page summary ===")
    if not per_page_counts:
        print("No pages retrieved.")
        return 1

    for page, counts in sorted(per_page_counts.items()):
        rb = counts.get("'\"reviewBody\"' (JSON)", 0)
        dp = counts.get("'datePublished'", 0)
        rt = counts.get("'review-title'", 0)
        sr = counts.get("'star-rating'", 0)
        blocks = counts.get("_blocks", 0)
        print(
            f"page {page}: "
            f"blocks={blocks} reviewBody={rb} datePublished={dp} "
            f"review-title={rt} star-rating={sr}"
        )

    # Verdict
    print("\n=== verdict ===")
    any_blocked = any(c.get("_blocks", 0) > 0 for c in per_page_counts.values())
    page1 = per_page_counts.get(1, {})
    has_dates_page1 = page1.get("'datePublished'", 0) >= 1 or page1.get(
        "ISO date yyyy-mm-dd", 0
    ) >= 5
    has_reviews_page1 = page1.get("'\"reviewBody\"' (JSON)", 0) >= 1 or page1.get(
        "'review-title'", 0
    ) >= 1

    if any_blocked:
        print(
            "BLOCKED on at least one page — the /site/reviews/name/ surface "
            "may have a different Akamai posture than the PDP surface. Next: "
            "try a slower pace, try stealth Playwright, or escalate to PDP-"
            "only coverage (no pagination)."
        )
    elif not has_reviews_page1:
        print(
            "NO REVIEW CONTENT visible on page 1. Either the review surface is "
            "client-hydrated (needs Playwright to render) or the URL shape is "
            "wrong. Inspect the saved fixture manually."
        )
    elif has_dates_page1 and has_reviews_page1:
        print(
            "GREEN — page 1 contains review bodies AND datePublished / ISO "
            "dates. Wave 2d is viable on this URL shape. Next: write parser "
            "that walks the review container + extracts body / title / "
            "author / rating / published_at."
        )
    else:
        print(
            "PARTIAL — page 1 has reviews but unclear date signal. Inspect "
            "the saved fixture to confirm where dates live (inline ISO? "
            "script blob? JSON-LD?) before finalizing the parser."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
