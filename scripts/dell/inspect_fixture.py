"""Inspect a saved Dell product-page fixture without refetching.

Offline companion to ``recon.py`` / ``probe_api.py``: loads a committed
fixture, dumps structural signals (JSON-LD Product, ``__NEXT_DATA__``,
tile ``data-oc`` values, DOM-attribute hints, heading outline) to stdout.
Useful when tweaking parsers without re-running live fetches.

Run from the repo root::

    .venv/Scripts/python.exe scripts/dell/inspect_fixture.py

See ``docs/ADDING_A_SOURCE.md`` for the recon methodology.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scrapers_lib.tier2._base import parse_inline_json, parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "tier2" / "fixtures" / "dell" / "alienware_aurora_16x.html"


def block_hits(html: str) -> list[str]:
    markers = [
        ("access denied", re.compile(r"<title>[^<]*access denied", re.I)),
        ("pardon interrupt", re.compile(r"pardon our interruption", re.I)),
        ("akamai edge", re.compile(r"errors\.edgesuite", re.I)),
        ("cf verify", re.compile(r"cf-browser-verification", re.I)),
        ("checking browser", re.compile(r"checking your browser", re.I)),
    ]
    return [name for name, pat in markers if pat.search(html)]


def main() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    print(f"html size: {len(html):,} chars")
    print(f"block markers: {block_hits(html) or 'none'}")

    # Title
    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"<title>: {m.group(1).strip() if m else '(none)'}")

    # JSON-LD
    products = parse_product_jsonld(html)
    print(f"\n[json-ld] Product objects: {len(products)}")
    for i, p in enumerate(products):
        keys = list(p.keys())
        print(f"  [{i}] @type={p.get('@type')} name={p.get('name','?')[:60]}")
        print(f"       keys={keys}")
        if "offers" in p:
            offers = p["offers"]
            if isinstance(offers, dict):
                print(f"       offers(dict) keys={list(offers.keys())}")
            elif isinstance(offers, list):
                print(f"       offers(list) n={len(offers)}")
                if offers:
                    print(f"       offers[0] keys={list(offers[0].keys())}")
        if "sku" in p:
            print(f"       sku={p['sku']}")
        if "mpn" in p:
            print(f"       mpn={p['mpn']}")
        if "brand" in p:
            print(f"       brand={p['brand']}")

    # __NEXT_DATA__
    nd = parse_inline_json(html, script_id="__NEXT_DATA__")
    print(f"\n[__NEXT_DATA__]: {'present' if nd else 'absent'}")
    if nd:
        print(f"  top-level keys: {list(nd.keys())}")
        # Try common Next.js paths
        pp = nd.get("props", {}).get("pageProps") if isinstance(nd.get("props"), dict) else None
        if pp:
            print(f"  props.pageProps keys: {list(pp.keys())[:25]}")

    # Other inline blobs
    for var in ("__INITIAL_STATE__", "__PRELOADED_STATE__", "__APOLLO_STATE__", "dataLayer"):
        blob = parse_inline_json(html, window_var=var)
        print(f"[window.{var}]: {'present' if blob else 'absent'}")

    # Look for any Dell-specific state blob
    dell_vars = re.findall(r'window\.(DELL[A-Z_]*|_DELL[A-Z_]*|spd[A-Z_]*)\s*=', html)
    if dell_vars:
        print(f"Dell-specific window vars found: {sorted(set(dell_vars))[:20]}")

    # DOM signals
    dom = {
        "data-testid values referencing 'preferred'": len(re.findall(r'data-testid="[^"]*preferred[^"]*"', html, re.I)),
        "'preferred-configuration' anywhere": len(re.findall(r"preferred[-_\s]configuration", html, re.I)),
        "'featured configuration'": len(re.findall(r"featured[-_\s]configuration", html, re.I)),
        "data-sku attrs": len(re.findall(r'data-sku="[^"]+"', html)),
        "config-tile CSS classes": len(re.findall(r'class="[^"]*config(?:uration)?[-_]?tile[^"]*"', html, re.I)),
        "'oc=' query params": len(re.findall(r'[?&]oc=[A-Za-z0-9_-]+', html)),
        "the word 'polaris'": len(re.findall(r"polaris", html, re.I)),
        "<h1> count": html.count("<h1"),
        "<table count": html.count("<table"),
        "<dl count": html.count("<dl "),
        "'$' price markers": len(re.findall(r'\$[0-9,]+\.\d{2}', html)),
    }
    print("\n[DOM signals]")
    for k, v in dom.items():
        print(f"  {k}: {v}")

    # Extract a preview of any tile-like data-testid values (top 20)
    tids = re.findall(r'data-testid="([^"]+)"', html)
    from collections import Counter
    counts = Counter(tids)
    print("\n[top 20 data-testid values by frequency]")
    for tid, n in counts.most_common(20):
        print(f"  {n:3d}  {tid}")

    # Capture any configuration-ish labels from visible text
    cfg_labels = re.findall(r'>([^<>]{3,80}(?:RTX|GeForce|Core i[3579]|Intel|AMD Ryzen|NVIDIA)[^<>]{0,60})<', html)
    print(f"\n[config label hints] {len(cfg_labels)} snippets")
    for s in cfg_labels[:10]:
        print(f"  - {s.strip()}")


if __name__ == "__main__":
    main()
