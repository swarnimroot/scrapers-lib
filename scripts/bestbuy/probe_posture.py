"""BestBuy PDP reconnaissance — step 1 of the ``ADDING_A_SOURCE.md`` §5 decision tree.

Plain ``httpx.get`` against a BestBuy URL with a current Chrome UA. No
stealth, no Playwright — discover what BestBuy looks like at the
lowest level before assuming any pattern. BestBuy reviews are Tier 3,
so a block is a plausible baseline; the point is to know *which*
block shape we face if any.

Goals (mapped to ``docs/ADDING_A_SOURCE.md``):

- §3.8 — Does BestBuy respond with real HTML to a minimally-configured
  browser request, or does it challenge us? Known gate shapes:
  Akamai bot challenge, "Access Denied", "Pardon Our Interruption"
  (Akamai's friendlier challenge variant).
- §3.3 / §3.4 / §3.5 — If real HTML, is review content SSR'd
  (JSON-LD reviews, inline blobs, per-review DOM nodes)?
- Baseline observation for the §5 decision tree — escalate to
  stealth + warming only on evidence.

Output (under ``tests/tier3/fixtures/bestbuy/``):

- ``<label>.html`` — raw response body on 200 OK.
- ``<label>_status{N}.html`` — non-200 body for post-mortem.

Run from the repo root::

    .venv/Scripts/python.exe scripts/bestbuy/probe_posture.py [URL] [LABEL]

Defaults to a gaming-laptop search URL — cheapest first probe that
reveals bot-gating before committing to a specific SKU.

See ``docs/ADDING_A_SOURCE.md`` §3 (techniques) and §5 (decision tree).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

from scrapers_lib.tier2.base import parse_inline_json, parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier3" / "fixtures" / "bestbuy"

# Keep in sync with scrapers_lib.core.playwright_base.DEFAULT_USER_AGENT.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

DEFAULT_URL = "https://www.bestbuy.com/site/searchpage.jsp?st=alienware+gaming+laptop"
DEFAULT_LABEL = "search_alienware_gaming_laptop"

BLOCK_MARKERS = [
    ("access denied", re.compile(r"<title>[^<]*access denied", re.I)),
    ("pardon interrupt", re.compile(r"pardon our interruption", re.I)),
    ("akamai edge", re.compile(r"errors\.edgesuite", re.I)),
    ("akamai reference", re.compile(r"reference\s*#[0-9a-f.]+", re.I)),
    ("bot challenge", re.compile(r"are you a robot|prove you are human", re.I)),
    ("captcha form", re.compile(r'action="[^"]*/captcha/', re.I)),
]

STATE_VARS = (
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
    "__NUXT__",
    "digitalData",
    "__REACT_QUERY_STATE__",
)


def block_hits(html: str) -> list[str]:
    return [name for name, pat in BLOCK_MARKERS if pat.search(html)]


def analyze(html: str) -> None:
    print(f"\nsize: {len(html):,} chars")
    blocks = block_hits(html)
    print(f"block markers: {blocks or 'none'}")

    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"<title>: {m.group(1).strip() if m else '(none)'}")

    # JSON-LD (§3.3)
    products = parse_product_jsonld(html)
    print(f"\n[json-ld] Product objects: {len(products)}")
    for i, p in enumerate(products[:3]):
        keys = list(p.keys())
        name = p.get("name") or ""
        if isinstance(name, str):
            name = name[:80]
        print(f"  [{i}] name={name}")
        if "review" in keys or "aggregateRating" in keys:
            print(f"       has review/rating keys: {[k for k in keys if 'review' in k.lower() or 'rating' in k.lower()]}")

    # Framework state blobs (§3.5)
    nd = parse_inline_json(html, script_id="__NEXT_DATA__")
    print(f"\n[__NEXT_DATA__]: {'present' if nd else 'absent'}")

    for var in STATE_VARS:
        blob = parse_inline_json(html, window_var=var)
        print(f"[window.{var}]: {'present' if blob else 'absent'}")

    # Review signals
    review_signals = {
        "'data-ugc' attrs": len(re.findall(r'data-ugc="', html)),
        "'review-item' occurrences": len(re.findall(r"review-item", html, re.I)),
        "'user-review' occurrences": len(re.findall(r"user-review", html, re.I)),
        "'itemprop=\"review\"' occurrences": len(re.findall(r'itemprop="review"', html)),
        "'data-track=\"Review' attrs": len(re.findall(r'data-track="Review', html)),
        "'\"reviewBody\"' (JSON)": len(re.findall(r'"reviewBody"', html)),
        "'star-rating' occurrences": len(re.findall(r"star-rating", html, re.I)),
    }
    print("\n[Review signals]")
    for k, v in review_signals.items():
        print(f"  {k}: {v}")

    # BestBuy-specific: SKU references on search pages
    skus = sorted(set(re.findall(r'data-sku-id="(\d{7})"', html)))
    if skus:
        print(f"\n[SKUs harvested]: {len(skus)} distinct (showing up to 15)")
        for s in skus[:15]:
            print(f"  https://www.bestbuy.com/site/-/{s}.p?skuId={s}")

    # DOM signals (§3.4)
    dom = {
        "<table count": html.count("<table"),
        "<dl count": html.count("<dl "),
        "<tr count": html.count("<tr"),
        "'specification' text": len(re.findall(r"specification", html, re.I)),
    }
    print("\n[DOM signals]")
    for k, v in dom.items():
        print(f"  {k}: {v}")

    # Verdict
    print("\n=== verdict ===")
    has_state_blob = bool(nd) or any(
        parse_inline_json(html, window_var=v) for v in STATE_VARS
    )
    if blocks:
        print(
            "BLOCKED — httpx response looks like a bot challenge. "
            "Next: escalate to Playwright + stealth, then + homepage warming."
        )
    elif skus and review_signals["'star-rating' occurrences"] >= 1:
        print(
            "SEARCH PAGE OK — SKUs + star-ratings visible. "
            "Next: re-probe against one SKU's PDP."
        )
    elif products and (
        review_signals["'\"reviewBody\"' (JSON)"] >= 1
        or review_signals["'data-track=\"Review' attrs"] >= 1
    ):
        print(
            "PDP OK — JSON-LD Product + review content found. "
            "Next: inspect review DOM shape and verify on 2nd unrelated SKU."
        )
    elif has_state_blob:
        print(
            "LIKELY SSR (state blob) — product model serialized into script. "
            "Next: inspect blob path to reviews."
        )
    else:
        print(
            "UNCLEAR — mixed signals. Inspect saved fixture manually before "
            "committing to a parser strategy."
        )


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    label = argv[2] if len(argv) > 2 else DEFAULT_LABEL

    print(f"[GET] {url}")
    try:
        resp = httpx.get(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 2

    print(f"status: {resp.status_code}")
    print(f"final URL: {resp.url}")
    print(f"content-type: {resp.headers.get('content-type', '(unset)')}")
    print(f"length: {len(resp.content):,} bytes")

    FIX.mkdir(parents=True, exist_ok=True)

    if resp.status_code != 200:
        out = FIX / f"{label}_status{resp.status_code}.html"
        out.write_bytes(resp.content)
        print(f"saved non-200 body: {out.relative_to(REPO)}")
        try:
            html = resp.text
        except Exception:
            return 1
        analyze(html)
        return 1

    html = resp.text
    out = FIX / f"{label}.html"
    out.write_text(html, encoding="utf-8")
    print(f"saved fixture: {out.relative_to(REPO)}")

    analyze(html)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
