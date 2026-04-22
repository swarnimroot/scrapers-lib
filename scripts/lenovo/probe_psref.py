"""Lenovo PSREF reconnaissance — step 1 of the ``ADDING_A_SOURCE.md`` §5 decision tree.

Plain ``httpx.get`` against a known Lenovo PSREF product URL with a current
Chrome UA. No stealth, no Playwright — the point is to discover what Lenovo
looks like at the lowest level.

Goals (mapped to ``docs/ADDING_A_SOURCE.md``):

- §3.8 — Does PSREF respond with real HTML to a minimally-configured browser
  request, or does it challenge us? → determines whether httpx is enough or
  we need Playwright + stealth.
- §3.3 / §3.4 / §3.5 — If the response is real HTML, is the spec data SSR'd
  (tables, ``<dl>`` pairs, JSON-LD, or a framework state blob)? → dictates
  which ``_base`` parser the fetcher reaches for.
- Baseline observation for the §5 decision tree — we should stop at step 1
  (dedicated spec-sheet site, SSR'd) if this probe confirms it. Escalate
  only on evidence.

Output (under ``tests/tier2/fixtures/lenovo/``):

- ``legion_pro_7_16afr10h.html`` — raw response body on 200 OK.
- ``legion_pro_7_16afr10h_status{N}.html`` — saved body on non-200 for
  post-mortem.

Run from the repo root::

    .venv/Scripts/python.exe scripts/lenovo/probe_psref.py

See ``docs/ADDING_A_SOURCE.md`` §3 for the techniques this script applies and
§5 for the decision tree it is walking.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

from scrapers_lib.tier2._base import parse_inline_json, parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "lenovo"

# Keep in sync with scrapers_lib.core.playwright_base.DEFAULT_USER_AGENT.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

URL = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec"
LABEL = "legion_pro_7_16afr10h"

BLOCK_MARKERS = [
    ("access denied", re.compile(r"<title>[^<]*access denied", re.I)),
    ("pardon interrupt", re.compile(r"pardon our interruption", re.I)),
    ("akamai edge", re.compile(r"errors\.edgesuite", re.I)),
    ("cf verify", re.compile(r"cf-browser-verification", re.I)),
    ("cf challenge", re.compile(r"cf-chl-", re.I)),
    ("checking browser", re.compile(r"checking your browser", re.I)),
]

STATE_VARS = (
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
    "__NUXT__",
    "dataLayer",
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
    for i, p in enumerate(products):
        keys = list(p.keys())
        name = (p.get("name") or "")
        if isinstance(name, str):
            name = name[:80]
        print(f"  [{i}] @type={p.get('@type')} name={name}")
        print(f"       keys={keys}")

    # Framework state blobs (§3.5)
    nd = parse_inline_json(html, script_id="__NEXT_DATA__")
    print(f"\n[__NEXT_DATA__]: {'present' if nd else 'absent'}")
    if nd:
        print(f"  top-level keys: {list(nd.keys())}")
        props = nd.get("props") if isinstance(nd.get("props"), dict) else None
        pp = props.get("pageProps") if isinstance(props, dict) and isinstance(props.get("pageProps"), dict) else None
        if pp:
            print(f"  props.pageProps keys: {list(pp.keys())[:25]}")

    for var in STATE_VARS:
        blob = parse_inline_json(html, window_var=var)
        print(f"[window.{var}]: {'present' if blob else 'absent'}")

    # Site-specific state hints
    vendor_vars = re.findall(
        r'window\.(lenovo[A-Za-z_]*|_lenovo[A-Za-z_]*|psref[A-Za-z_]*)\s*=',
        html,
        re.I,
    )
    if vendor_vars:
        print(f"Lenovo/PSREF-specific window vars: {sorted(set(vendor_vars))[:20]}")

    # DOM signals (§3.4)
    dom = {
        "<table count": html.count("<table"),
        "<dl count": html.count("<dl "),
        "<tr count": html.count("<tr"),
        "<dt count": html.count("<dt"),
        "<th count": html.count("<th"),
        "'specification' text (any case)": len(re.findall(r"specification", html, re.I)),
        "'Processor' occurrences": len(re.findall(r"\bprocessor\b", html, re.I)),
        "'Memory' occurrences": len(re.findall(r"\bmemory\b", html, re.I)),
        "'Graphics' occurrences": len(re.findall(r"\bgraphics\b", html, re.I)),
    }
    print("\n[DOM signals]")
    for k, v in dom.items():
        print(f"  {k}: {v}")

    # §3.2 technique — attribute values mentioning 'spec'
    spec_attrs = re.findall(r'([a-z_-]+="[^"]*spec[^"]*")', html, re.I)
    distinct = sorted(set(spec_attrs))
    print(
        f"\n[attribute values mentioning 'spec']: {len(distinct)} distinct "
        "(showing up to 15)"
    )
    for s in distinct[:15]:
        print(f"  {s[:160]}")

    # Heading outline
    headings = re.findall(r"<h([1-3])[^>]*>([^<]{1,120})</h\1>", html, re.I)
    print(f"\n[headings h1-h3]: {len(headings)} total (showing first 20)")
    for lvl, text in headings[:20]:
        print(f"  h{lvl}  {text.strip()}")

    # Verdict — drives the next recon step.
    print("\n=== verdict ===")
    has_state_blob = bool(nd) or any(
        parse_inline_json(html, window_var=v) for v in STATE_VARS
    )
    if blocks:
        print(
            "BLOCKED — httpx response looks like a bot challenge. "
            "Next: Playwright + stealth probe (with homepage warming if needed)."
        )
    elif dom["<table count"] >= 3 and dom["'Processor' occurrences"] >= 1:
        print(
            "LIKELY SSR (tables) — spec content appears to live in the HTML. "
            "Next: write a pure-parse function on top of _base.parse_spec_table "
            "and verify against a second Lenovo product URL."
        )
    elif has_state_blob and dom["'Processor' occurrences"] >= 1:
        print(
            "LIKELY SSR (state blob) — product model appears serialized into a "
            "<script> tag. Next: inspect the blob path to spec data, then write "
            "a parser on top of _base.parse_inline_json."
        )
    elif dom["<table count"] == 0 and not has_state_blob:
        print(
            "LIKELY SPA — small/structureless response, no tables, no state blob. "
            "Specs are probably XHR-hydrated. Next: Playwright probe (no stealth "
            "to start) with Network-tab tracing to find the data endpoint."
        )
    else:
        print(
            "UNCLEAR — mixed signals. Inspect the saved fixture manually before "
            "committing to a parser strategy."
        )


def main() -> int:
    print(f"[GET] {URL}")
    try:
        resp = httpx.get(
            URL,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
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
        out = FIX / f"{LABEL}_status{resp.status_code}.html"
        out.write_bytes(resp.content)
        print(f"saved non-200 body: {out.relative_to(REPO)}")
        # Still analyze — a block page is informative.
        try:
            html = resp.text
        except Exception:
            return 1
        analyze(html)
        return 1

    html = resp.text
    out = FIX / f"{LABEL}.html"
    out.write_text(html, encoding="utf-8")
    print(f"saved fixture: {out.relative_to(REPO)}")

    analyze(html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
