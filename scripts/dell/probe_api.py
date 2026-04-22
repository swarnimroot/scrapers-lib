"""Fetch each known Aurora tile's techspecs response via Dell's internal API.

After stealth + homepage warming, calls ``/csbapi/unifiedpd/techspecs/...``
for each hard-coded tile SKU through the same Playwright browser context
(so Akamai cookies accompany the request). Saves the response HTML
fragments as committed test fixtures.

Run from the repo root::

    .venv/Scripts/python.exe scripts/dell/probe_api.py

See ``docs/ADDING_A_SOURCE.md`` for the recon methodology.
"""

from __future__ import annotations

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
AURORA = (
    "https://www.dell.com/en-us/shop/dell-laptops/alienware-16x-aurora-gaming-laptop/"
    "spd/alienware-aurora-ac16251-gaming-laptop"
)
API_BASE = "https://www.dell.com"
ENDPOINTS = [
    "/csbapi/unifiedpd/techspecs/en/us/bsd/04/useac16251hbtshqfq",
    "/csbapi/unifiedpd/techspecs/en/us/bsd/04/useac16251hbtshqmy",
    "/csbapi/unifiedpd/techspecs/en/us/bsd/04/useac16251wmlkcto03",
]


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
            time.sleep(3)
            # Navigate to product
            page.goto(AURORA, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)
            page.close()

            # Hit the API using the browser context (inherits cookies)
            for i, ep in enumerate(ENDPOINTS):
                url = API_BASE + ep
                r = ctx.request.get(url, headers={
                    "User-Agent": UA,
                    "Accept": "application/json, text/html, */*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": AURORA,
                })
                body = r.text()
                ctype = r.headers.get("content-type", "?")
                print(f"\n--- endpoint {i}: {ep} ---")
                print(f"status: {r.status}")
                print(f"content-type: {ctype}")
                print(f"body length: {len(body):,} chars")
                print(f"first 300 chars: {body[:300]!r}")

                # Save
                sku = ep.rsplit("/", 1)[-1]
                out = FIX / f"techspecs_{sku}.txt"
                out.write_text(body, encoding="utf-8")
                print(f"saved: {out}")
        finally:
            ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
