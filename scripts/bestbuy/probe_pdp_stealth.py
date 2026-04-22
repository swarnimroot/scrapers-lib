"""BestBuy PDP stealth-Playwright probe — §3.8 escalation.

Plain httpx against a BestBuy PDP returned ``RemoteProtocolError:
Server disconnected without sending a response`` — classic
Akamai JA3/TLS-fingerprint drop at the transport layer. This probe
escalates to stealth Playwright (the Dell pattern): launch a
persistent-profile Chromium with fingerprint masking, warm against
the homepage so Akamai cookies settle, then navigate the target PDP.

Three outcomes to distinguish:

- 200 with real review DOM → proceed with stealth Playwright fetcher
  (mirror Dell's pattern — one session, warm, then navigate).
- Navigation fails with ``ERR_HTTP2_PROTOCOL_ERROR`` / similar TLS-
  layer drop → the HP-class wall. Playwright alone isn't enough;
  escalate to ``curl_cffi`` (new dep, user approval needed) or defer.
- 200 but the review container is empty / XHR-hydrated only → the
  PDP ships a shell; reviews live behind a follow-up XHR that
  Playwright can still observe via ``page.context.request``.

Output (under ``tests/tier3/fixtures/bestbuy/``):

- ``<label>_stealth.html`` — post-navigation rendered DOM on success.
- Status messages describe which outcome we hit.

Run from the repo root::

    .venv/Scripts/python.exe scripts/bestbuy/probe_pdp_stealth.py [URL] [LABEL]
"""

from __future__ import annotations

import re
import sys
import time
import traceback
from pathlib import Path

from scrapers_lib.core.playwright_base import stealth_context

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier3" / "fixtures" / "bestbuy"

DEFAULT_URL = "https://www.bestbuy.com/site/alienware/6628371.p?skuId=6628371"
DEFAULT_LABEL = "pdp_6628371"

HOME_URL = "https://www.bestbuy.com/"

BLOCK_MARKERS = [
    ("pardon interrupt", re.compile(r"pardon our interruption", re.I)),
    ("akamai reference", re.compile(r"reference\s*#[0-9a-f.]+", re.I)),
    ("access denied", re.compile(r"<title>[^<]*access denied", re.I)),
]


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    label = argv[2] if len(argv) > 2 else DEFAULT_LABEL

    FIX.mkdir(parents=True, exist_ok=True)

    print(f"[stealth] launching Chromium with persistent profile for www.bestbuy.com")
    try:
        with stealth_context(
            profiles_dir=REPO / ".profiles",
            domain="www.bestbuy.com",
        ) as page:
            print(f"[warm] {HOME_URL}")
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(3)
            print(f"[goto] {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)
            html = page.content()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2

    print(f"size: {len(html):,} chars")

    blocks = [name for name, pat in BLOCK_MARKERS if pat.search(html)]
    print(f"block markers: {blocks or 'none'}")

    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"<title>: {m.group(1).strip() if m else '(none)'}")

    review_signals = {
        "'reviewBody' (JSON-LD)": len(re.findall(r'"reviewBody"', html)),
        "'data-track=\"Review' attrs": len(re.findall(r'data-track="Review', html)),
        "'class=\"review-item' occurrences": len(re.findall(r'class="[^"]*review-item', html, re.I)),
        "'ugc-review' occurrences": len(re.findall(r"ugc-review", html, re.I)),
        "'user-generated-content' occurrences": len(re.findall(r"user-generated-content", html, re.I)),
        "'Customer Reviews' heading": len(re.findall(r"Customer Reviews", html)),
        "'aggregateRating' (JSON-LD)": len(re.findall(r"aggregateRating", html)),
    }
    print("\n[review signals]")
    for k, v in review_signals.items():
        print(f"  {k}: {v}")

    out = FIX / f"{label}_stealth.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nsaved: {out.relative_to(REPO)}")

    if blocks:
        print(
            "\n=== verdict ===\nBLOCKED even with stealth + warming. "
            "Same class as HP's ERR_HTTP2_PROTOCOL_ERROR. "
            "Upgrade path: curl_cffi (new dep, user approval) or defer."
        )
        return 1
    if review_signals["'reviewBody' (JSON-LD)"] + review_signals["'data-track=\"Review' attrs"] >= 1:
        print(
            "\n=== verdict ===\nOK — stealth + warming reached the PDP and "
            "review content is present. Proceed with stealth Playwright "
            "fetcher mirroring the Dell pattern."
        )
        return 0
    print(
        "\n=== verdict ===\nReached the PDP but reviews may be XHR-hydrated. "
        "Inspect the saved fixture manually or add a scroll+wait step."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
