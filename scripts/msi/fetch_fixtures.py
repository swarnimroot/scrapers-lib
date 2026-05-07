"""Fetch real MSI fixtures (warm session + curl_cffi + HTTP/1.1).

Saves under tests/tier2/fixtures/msi/. Run once to seed; checked-in
fixtures are the source of truth for unit tests.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from curl_cffi import CurlHttpVersion, requests

OUT = Path(__file__).resolve().parents[2] / "tests" / "tier2" / "fixtures" / "msi"
OUT.mkdir(parents=True, exist_ok=True)

HOME = "https://us.msi.com/"

TARGETS = [
    # AI/Stealth — JSON-LD ItemList path
    (
        "stealth_16_ai_plus_b3wx_main.html",
        "https://us.msi.com/Laptop/Stealth-16-AI-Plus-B3WX",
    ),
    # AI/Stealth — /Specification path (universal across product lines;
    # captured to back the new Specification-first default for AI SKUs).
    (
        "stealth_16_ai_plus_b3wx_specification.html",
        "https://us.msi.com/Laptop/Stealth-16-AI-Plus-B3WX/Specification",
    ),
    # Gaming — /Specification path with multiple SKUs
    (
        "raider_16_max_hx_b2wx_specification.html",
        "https://us.msi.com/Laptop/Raider-16-Max-HX-B2WX/Specification",
    ),
    # Gaming main page (JSON-LD-absent fallback evidence)
    (
        "raider_16_max_hx_b2wx_main.html",
        "https://us.msi.com/Laptop/Raider-16-Max-HX-B2WX",
    ),
    # Second gaming /Specification page for generality check
    (
        "crosshair_16_hx_e14wx_specification.html",
        "https://us.msi.com/Laptop/Crosshair-16-HX-E14WX/Specification",
    ),
]


def main() -> int:
    with requests.Session(
        impersonate="chrome",
        http_version=CurlHttpVersion.V1_1,
    ) as s:
        try:
            r = s.get(HOME, timeout=30)
            print(f"warm us.msi.com -> {r.status_code} ({len(r.text)} bytes)")
        except Exception as e:
            print(f"warm failed: {e}")
            return 1
        time.sleep(1)

        for name, url in TARGETS:
            time.sleep(1)
            try:
                r = s.get(
                    url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": HOME,
                    },
                    timeout=30,
                )
            except Exception as e:
                print(f"FAIL {url}: {e}")
                return 1
            print(f"{url} -> {r.status_code} ({len(r.text)} bytes)")
            if r.status_code != 200:
                print(f"  abort — non-200 on {url}")
                return 1
            (OUT / name).write_text(r.text, encoding="utf-8")
            print(f"  wrote {name}")

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
