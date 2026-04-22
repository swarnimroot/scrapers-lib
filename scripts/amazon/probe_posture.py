"""Amazon product-page reconnaissance — step 1 of the ``ADDING_A_SOURCE.md`` §5 decision tree.

Plain ``httpx.get`` against one Amazon URL with a current Chrome UA. No
stealth, no Playwright — we discover what Amazon looks like at the
lowest level before assuming any pattern. Amazon is Tier 3, so a block
is the expected baseline; the point is to know *which* block shape we
face.

Goals (mapped to ``docs/ADDING_A_SOURCE.md``):

- §3.8 — Does Amazon respond with real HTML to a minimally-configured
  browser request, or does it challenge us? Well-known bot gates:
  "robot check", Automated Access Agreement, CAPTCHA challenge.
- §3.3 / §3.4 / §3.5 — If the response is real HTML, is product data
  SSR'd (JSON-LD, inline ``<script>`` blobs, table-shaped spec DOM)?
- Baseline observation for the §5 decision tree — escalate to
  stealth + warming only on evidence.

Output (under ``tests/tier3/fixtures/amazon/``):

- ``<label>.html`` — raw response body on 200 OK.
- ``<label>_status{N}.html`` — non-200 body for post-mortem.

Run from the repo root::

    .venv/Scripts/python.exe scripts/amazon/probe_posture.py [URL] [LABEL]

Defaults to the search page ``amazon.com/s?k=alienware+gaming+laptop``
when no arguments are given — cheapest safe first probe that reveals
whether bot gating is on before committing to a specific ASIN.

See ``docs/ADDING_A_SOURCE.md`` §3 (techniques) and §5 (decision tree).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

from scrapers_lib.tier2._base import parse_inline_json, parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier3" / "fixtures" / "amazon"

# Keep in sync with scrapers_lib.core.playwright_base.DEFAULT_USER_AGENT.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

DEFAULT_URL = "https://www.amazon.com/s?k=alienware+gaming+laptop"
DEFAULT_LABEL = "search_alienware_gaming_laptop"

# Amazon-specific and shared bot-gate signatures. These must be tight
# enough to avoid false positives on legitimate PDP HTML (which contains
# stock error-UI templates and the "captcha" word in referrer scripts).
# All anchored against block-page shape, not arbitrary occurrences.
BLOCK_MARKERS = [
    ("robot check", re.compile(r"<title>\s*robot check", re.I)),
    ("automated access", re.compile(r"automated access to amazon data", re.I)),
    ("sorry something went wrong title", re.compile(r"<title>\s*sorry!?\s*something went wrong", re.I)),
    ("validateCaptcha form", re.compile(r"action=\"[^\"]*/errors/validateCaptcha\"", re.I)),
    ("enter characters prompt", re.compile(r"type the characters you see in this image", re.I)),
    ("access denied title", re.compile(r"<title>[^<]*access denied", re.I)),
]

# Common SPA state-container variables. Amazon's product pages have
# historically used `P.when(...)` and inline `data-a-state` attributes
# rather than a canonical __NEXT_DATA__-style payload, but we probe the
# usual suspects too in case of redesign.
STATE_VARS = (
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
    "__NUXT__",
    "digitalData",
    "ue_sid",
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
        print(f"  [{i}] @type={p.get('@type')} name={name}")
        print(f"       keys={keys}")

    # Framework state blobs (§3.5)
    nd = parse_inline_json(html, script_id="__NEXT_DATA__")
    print(f"\n[__NEXT_DATA__]: {'present' if nd else 'absent'}")

    for var in STATE_VARS:
        blob = parse_inline_json(html, window_var=var)
        print(f"[window.{var}]: {'present' if blob else 'absent'}")

    # Amazon-specific signals
    amazon_signals = {
        "'twister' occurrences": len(re.findall(r"twister", html, re.I)),
        "'data-asin' attrs": len(re.findall(r'data-asin="[A-Z0-9]{10}"', html)),
        "'productDetails' occurrences": len(re.findall(r"productDetails", html, re.I)),
        "'featurebullets' occurrences": len(re.findall(r"featurebullets", html, re.I)),
        "'acrCustomerReview' occurrences": len(re.findall(r"acrCustomerReview", html, re.I)),
        "'P.when(' calls": len(re.findall(r"P\.when\(", html)),
        "'data-a-state' attrs": len(re.findall(r'data-a-state="', html)),
    }
    print("\n[Amazon signals]")
    for k, v in amazon_signals.items():
        print(f"  {k}: {v}")

    # Extract ASINs (search result surface)
    asins = sorted(set(re.findall(r'data-asin="([A-Z0-9]{10})"', html)))
    if asins:
        print(f"\n[ASINs harvested]: {len(asins)} distinct (showing up to 15)")
        for a in asins[:15]:
            print(f"  https://www.amazon.com/dp/{a}")

    # DOM signals (§3.4)
    dom = {
        "<table count": html.count("<table"),
        "<dl count": html.count("<dl "),
        "<tr count": html.count("<tr"),
        "'specification' text (any case)": len(re.findall(r"specification", html, re.I)),
        "'Processor' occurrences": len(re.findall(r"\bprocessor\b", html, re.I)),
        "'Memory' occurrences": len(re.findall(r"\bmemory\b", html, re.I)),
        "'Graphics' occurrences": len(re.findall(r"\bgraphics\b", html, re.I)),
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
    elif amazon_signals["'data-asin' attrs"] >= 5:
        print(
            "SEARCH PAGE OK — many data-asin tiles present. "
            "Next: re-probe against one harvested ASIN's /dp/ PDP."
        )
    elif products and amazon_signals["'featurebullets' occurrences"] >= 1:
        print(
            "PDP OK — JSON-LD Product + featurebullets container found. "
            "Next: §5.7 generality check on a second unrelated ASIN, then "
            "design the parser."
        )
    elif has_state_blob:
        print(
            "LIKELY SSR (state blob) — product model may be serialized into a "
            "<script> tag. Next: inspect the blob path to product/review data."
        )
    elif dom["<table count"] == 0 and not products:
        print(
            "LIKELY SPA or shallow response — no tables, no JSON-LD. "
            "Specs/reviews probably XHR-hydrated. Next: Playwright probe."
        )
    else:
        print(
            "UNCLEAR — mixed signals. Inspect the saved fixture manually before "
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
                "Accept-Encoding": "gzip, deflate, br",
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
