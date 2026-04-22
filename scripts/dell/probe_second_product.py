"""Generality check: verify the Dell techspecs-API pattern on a second product line.

Navigates candidate category pages until a non-Aurora SPD link surfaces,
fetches that product page, extracts its ``[data-oc]`` tile SKUs and
``data-url`` techspecs endpoints, and calls one endpoint to confirm the
same HTML-fragment response shape. This is how we locked in that the Dell
pattern is site-wide, not Alienware-specific.

Run from the repo root::

    .venv/Scripts/python.exe scripts/dell/probe_second_product.py

See ``docs/ADDING_A_SOURCE.md`` for the recon methodology.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "dell"
PROFILES = REPO / ".profiles"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

CANDIDATE_CATEGORIES = [
    "https://www.dell.com/en-us/shop/scc/sc/laptops",
    "https://www.dell.com/en-us/shop/laptops-2-in-1-computers/new-xps-laptops/ar/6787",
    "https://www.dell.com/en-us/shop/dell-laptops",
    "https://www.dell.com/en-us/shop/dell-laptops/sr/laptops",
]


def harvest_spd_links(page) -> list[str]:
    # Scroll to encourage lazy loaders
    for y in range(0, 6000, 700):
        page.evaluate(f"window.scrollTo(0, {y})")
        time.sleep(0.4)
    time.sleep(3)
    hrefs = page.eval_on_selector_all(
        "a[href*='/spd/']", "els => els.map(e => e.getAttribute('href'))"
    )
    # Normalize and dedup
    seen = []
    for h in hrefs or []:
        if not h:
            continue
        if "alienware-aurora-ac16251" in h:
            continue
        if h.startswith("/"):
            h = "https://www.dell.com" + h
        if h.startswith("https://www.dell.com") and "/spd/" in h and h not in seen:
            seen.append(h)
    return seen


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with Stealth().use_sync(sync_playwright()) as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILES / "www.dell.com"),
            headless=True,
            user_agent=UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            page = ctx.new_page()
            # Warm
            page.goto("https://www.dell.com/en-us/", wait_until="domcontentloaded", timeout=60_000)
            time.sleep(2)
            page.close()

            found: list[str] = []
            for cat in CANDIDATE_CATEGORIES:
                page = ctx.new_page()
                try:
                    print(f"[category] {cat}")
                    page.goto(cat, wait_until="domcontentloaded", timeout=60_000)
                    time.sleep(3)
                    links = harvest_spd_links(page)
                    print(f"  found {len(links)} SPD links")
                    for h in links[:5]:
                        print(f"    {h}")
                    found.extend(links)
                    if found:
                        break
                finally:
                    page.close()

            if not found:
                print("FAIL: no second product found across candidate categories")
                return 1

            second_url = found[0]
            print(f"\n[chosen] second product: {second_url}")

            # Fetch the product page, extract data-oc values
            page = ctx.new_page()
            page.goto(second_url, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)
            html = page.content()
            page.close()

            m = re.search(r"/spd/([^/?#]+)", second_url)
            slug = m.group(1) if m else "product2"
            (FIX / f"{slug}.html").write_text(html, encoding="utf-8")
            print(f"saved product HTML: {FIX / f'{slug}.html'}")

            # Extract data-oc values and data-url tech-specs endpoints
            ocs = sorted(set(re.findall(r'data-oc="([a-zA-Z0-9_-]+)"', html)))
            endpoints = sorted(set(
                re.findall(r'data-url="(/csbapi/unifiedpd/techspecs/[^"]+)"', html)
            ))
            print(f"distinct data-oc values: {len(ocs)}")
            for oc in ocs[:5]:
                print(f"  {oc}")
            print(f"distinct techspecs endpoints in DOM: {len(endpoints)}")
            for ep in endpoints[:5]:
                print(f"  {ep}")

            # Call first endpoint
            if endpoints:
                url = "https://www.dell.com" + endpoints[0]
                r = ctx.request.get(url, headers={
                    "User-Agent": UA,
                    "Accept": "application/json, text/html, */*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": second_url,
                })
                body = r.text()
                print(f"\n[api] {endpoints[0]}")
                print(f"  status: {r.status}")
                print(f"  content-type: {r.headers.get('content-type','?')}")
                print(f"  body length: {len(body):,} chars")
                print(f"  preview: {body[:300]!r}")
                sku = endpoints[0].rsplit("/", 1)[-1]
                (FIX / f"techspecs_{sku}.txt").write_text(body, encoding="utf-8")
                print(f"  saved: {FIX / f'techspecs_{sku}.txt'}")
        finally:
            ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
