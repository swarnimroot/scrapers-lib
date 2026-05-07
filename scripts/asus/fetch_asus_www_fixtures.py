"""ASUS www (non-ROG) fixture-capture probe.

Fetches techspec pages from ``www.asus.com/<region>/laptops/...`` for three
product families (Zenbook, Vivobook, TUF Gaming) using plain httpx and the
fetcher's ``_DEFAULT_USER_AGENT`` for header parity.

Saves under ``tests/tier2/fixtures/asus_www/`` and reports size + presence
of the ``__NUXT__=(function`` IIFE marker and ``TechSpec__`` class family.

Run from repo root::

    .venv/Scripts/python.exe scripts/asus/fetch_asus_www_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "asus_www"

# Pulled from scrapers_lib/tier2/asus.py for parity.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

PROBES = [
    (
        "https://www.asus.com/us/laptops/for-home/zenbook/asus-zenbook-14-ux3405/techspec/",
        "zenbook_14_ux3405",
    ),
    (
        "https://www.asus.com/us/laptops/for-home/vivobook/vivobook-16-laptop-f1605/techspec/",
        "vivobook_16_f1605",
    ),
    (
        "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2025/techspec/",
        "tuf_gaming_a16_2025",
    ),
]


def get(url: str) -> httpx.Response:
    return httpx.get(
        url,
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30.0,
    )


def analyze(html: str) -> dict:
    has_iife = "__NUXT__=(function" in html
    techspec_hits = html.count("TechSpec__")
    return {
        "size": len(html),
        "has_nuxt_iife": has_iife,
        "techspec_class_hits": techspec_hits,
    }


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)

    for url, label in PROBES:
        print(f"\n[GET] {url}")
        try:
            r = get(url)
        except httpx.HTTPError as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            continue
        print(f"  status: {r.status_code}")
        if r.status_code != 200:
            print(f"  -> non-200 ({r.status_code}); needs replacement URL recon")
            continue
        out = FIX / f"{label}.html"
        out.write_text(r.text, encoding="utf-8")
        info = analyze(r.text)
        kb = info["size"] / 1024
        print(f"  saved: {out.relative_to(REPO)}  ({kb:.1f} KB)")
        print(f"    has __NUXT__=(function: {info['has_nuxt_iife']}")
        print(f"    TechSpec__ class hits:  {info['techspec_class_hits']}")
        if info["size"] < 100 * 1024:
            print(f"    !! UNDER 100KB — suspicious; may be error page or shell")
        if not info["has_nuxt_iife"]:
            print(f"    !! NO __NUXT__ IIFE — anchor pattern needs revisit")

    return 0


if __name__ == "__main__":
    sys.exit(main())
